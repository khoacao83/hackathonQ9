const fs = require('fs').promises;
const { execFile } = require('child_process');
const path = require('path');
const vscode = require('vscode');

// ─────────────────────────────────────────────
//  Extension lifecycle
// ─────────────────────────────────────────────

function activate(context) {
  const fixCommand = vscode.commands.registerCommand(
    'aiCodeAssembly.safePatchCurrentFile',
    async () => {
      try {
        await runAssemblyLinePipeline();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        void vscode.window.showErrorMessage(`AI Code Assembly failed: ${message}`);
      }
    }
  );

  const showSummaryCommand = vscode.commands.registerCommand(
    'aiCodeAssembly.showRunSummary',
    async () => {
      try {
        await showRunSummary();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        void vscode.window.showErrorMessage(`AI Code Assembly summary failed: ${message}`);
      }
    }
  );

  context.subscriptions.push(fixCommand, showSummaryCommand);
}

function deactivate() {
  // no-op
}

// ─────────────────────────────────────────────
//  Main pipeline: Extension-driven flow
// ─────────────────────────────────────────────

async function runAssemblyLinePipeline() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    throw new Error('No active editor. Open a file first.');
  }

  const workspaceFolder = vscode.workspace.getWorkspaceFolder(editor.document.uri);
  if (!workspaceFolder) {
    throw new Error('Active file is not inside a workspace folder.');
  }

  const workspaceRoot = workspaceFolder.uri.fsPath;
  const activeAbs = editor.document.uri.fsPath;

  // ── Step 1: User nhập task description ──
  const task = await vscode.window.showInputBox({
    prompt: 'Describe the coding task for this file',
    placeHolder: 'Fix export_report when data is empty',
    ignoreFocusOut: true,
  });

  if (!task) {
    return;
  }

  const detectedProjectRoot = detectProjectRootFromActiveFile(workspaceRoot, activeAbs);
  const projectDefault = detectedProjectRoot || 'demo_project';
  const projectInputRaw = await vscode.window.showInputBox({
    prompt: 'Project root relative to workspace',
    value: projectDefault,
    ignoreFocusOut: true,
  });

  if (projectInputRaw === undefined) {
    return;
  }

  const projectInput = sanitizeProjectInput(projectInputRaw) || projectDefault;
  const projectRootRel = normalizeRel(projectInput);
  let projectAbs = path.isAbsolute(projectInput)
    ? path.resolve(projectInput)
    : path.resolve(workspaceRoot, projectRootRel);

  if (!isPathInside(projectAbs, activeAbs) && detectedProjectRoot) {
    projectAbs = path.resolve(workspaceRoot, detectedProjectRoot);
    void vscode.window.showWarningMessage(
      `Selected project root did not contain active file. Auto-switched to ${detectedProjectRoot}.`
    );
  }

  const targetFileRel = normalizeRel(path.relative(projectAbs, activeAbs));
  if (targetFileRel.startsWith('..') || path.isAbsolute(targetFileRel)) {
    throw new Error(
      `Active file is outside selected project root. Active file: ${activeAbs} | Project root: ${projectAbs}`
    );
  }

  const projectArg = isPathInside(workspaceRoot, projectAbs)
    ? normalizeRel(path.relative(workspaceRoot, projectAbs))
    : projectAbs;

  // ── Step 2: Gọi Python context service (graph/AST/context) ──
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: 'AI Code Assembly Line',
      cancellable: false,
    },
    async (progress) => {
      progress.report({ message: '[1/4] Scanning & building context...' });

      let contextData;
      try {
        contextData = await callContextService(workspaceRoot, projectArg, targetFileRel);
      } catch (err) {
        throw new Error(`Context service failed: ${err.message || err}`);
      }

      const relatedFiles = contextData.related_files || [];
      const optimizedContext = contextData.optimized_context || '';
      const tokenMetrics = contextData.token_metrics || {};

      const output = vscode.window.createOutputChannel('AI Code Assembly');
      output.clear();
      output.appendLine('AI Code Assembly Line - Extension Pipeline');
      output.appendLine('='.repeat(48));
      output.appendLine(`Related files: ${relatedFiles.join(', ')}`);
      output.appendLine(`Raw tokens: ${tokenMetrics.raw_tokens || 'N/A'}`);
      output.appendLine(`Optimized tokens: ${tokenMetrics.optimized_tokens || 'N/A'}`);
      output.appendLine(`Saved: ${tokenMetrics.saved_percent || 0}%`);
      output.appendLine('');

      // ── Step 3: Gọi Copilot LM (hoặc Mock fallback) ──
      progress.report({ message: '[2/4] Generating patch via Copilot LM...' });

      const docText = editor.document.getText();
      let patchText = '';
      const model = await getCopilotModel();

      if (model) {
        const prompt = buildPrompt(targetFileRel, task, docText, optimizedContext);
        patchText = await requestPatchText(model, prompt);
        patchText = normalizeModelPatchOutput(patchText).trim();

        if (!patchText) {
          throw new Error('Model returned empty patch text.');
        }

        if (!isUnifiedDiffPatch(patchText)) {
          const repairPrompt = buildRepairPrompt(patchText, targetFileRel);
          const repairedText = await requestPatchText(model, repairPrompt);
          const repairedPatch = normalizeModelPatchOutput(repairedText).trim();

          if (!isUnifiedDiffPatch(repairedPatch)) {
            throw new Error(
              'Model output is not a valid unified diff (missing --- a/, +++ b/, @@ headers). Cancelled.'
            );
          }
          patchText = repairedPatch;
        }

        output.appendLine('LLM backend: Copilot');
      } else {
        void vscode.window.showWarningMessage(
          'Cannot connect to GitHub Copilot (not signed in). Using mock patch.'
        );
        patchText = generateMockPatch(targetFileRel, task);
        output.appendLine('LLM backend: Mock (Copilot unavailable)');
      }

      output.appendLine('');
      output.appendLine('Generated patch:');
      output.appendLine(patchText);
      output.show(true);

      // ── Step 4: Parse patch & show Diff Preview ──
      progress.report({ message: '[3/4] Preparing diff preview...' });

      const originalContent = docText;
      const patchedContent = applyUnifiedDiffToText(originalContent, patchText, targetFileRel);

      if (patchedContent === originalContent) {
        void vscode.window.showWarningMessage('Patch produced no changes to the file.');
        return;
      }

      // Ghi file tạm cho diff preview
      const tmpDir = path.join(workspaceRoot, '.tmp');
      await fs.mkdir(tmpDir, { recursive: true });

      const patchedPreviewPath = path.join(tmpDir, 'preview_patched' + path.extname(activeAbs));
      await fs.writeFile(patchedPreviewPath, patchedContent, 'utf-8');

      // Lưu patch.diff
      const patchDiffPath = path.join(tmpDir, 'copilot_patch.diff');
      await fs.writeFile(patchDiffPath, patchText + '\n', 'utf-8');

      // Mở VS Code Diff Editor
      const originalUri = editor.document.uri;
      const patchedUri = vscode.Uri.file(patchedPreviewPath);

      await vscode.commands.executeCommand(
        'vscode.diff',
        originalUri,
        patchedUri,
        `AI Patch Preview: ${path.basename(activeAbs)} (Original ↔ Patched)`
      );

      // ── Step 5: User Accept / Reject ──
      progress.report({ message: '[4/4] Waiting for your approval...' });

      const decision = await vscode.window.showInformationMessage(
        `AI Code Assembly: Apply patch to ${path.basename(activeAbs)}?`,
        { modal: true, detail: `Task: ${task}\nChanged file: ${targetFileRel}\nOptimized tokens: ${tokenMetrics.optimized_tokens || 'N/A'}` },
        'Accept',
        'Reject'
      );

      if (decision === 'Accept') {
        // Apply trực tiếp vào file gốc
        const edit = new vscode.WorkspaceEdit();
        const fullRange = new vscode.Range(
          editor.document.positionAt(0),
          editor.document.positionAt(editor.document.getText().length)
        );
        edit.replace(editor.document.uri, fullRange, patchedContent);
        await vscode.workspace.applyEdit(edit);
        await editor.document.save();

        void vscode.window.showInformationMessage(
          `✅ Patch applied to ${path.basename(activeAbs)}`
        );

        output.appendLine('');
        output.appendLine('Decision: ACCEPTED – patch applied to original file.');

        // Ghi evidence report
        await writeEvidenceReport(workspaceRoot, {
          task,
          targetFile: targetFileRel,
          relatedFiles,
          tokenMetrics,
          patchText,
          status: 'applied',
          decision: 'ACCEPTED',
          llmBackend: model ? 'copilot' : 'mock',
        });

      } else {
        void vscode.window.showInformationMessage(
          `❌ Patch rejected. No changes were made.`
        );

        output.appendLine('');
        output.appendLine('Decision: REJECTED – no changes applied.');

        await writeEvidenceReport(workspaceRoot, {
          task,
          targetFile: targetFileRel,
          relatedFiles,
          tokenMetrics,
          patchText,
          status: 'rejected',
          decision: 'REJECTED',
          llmBackend: model ? 'copilot' : 'mock',
        });
      }

      // Dọn file tạm
      try {
        await fs.unlink(patchedPreviewPath);
      } catch (_) {
        // ignore
      }
    }
  );
}

// ─────────────────────────────────────────────
//  Python Context Service caller
// ─────────────────────────────────────────────

function callContextService(workspaceRoot, projectArg, targetFileRel) {
  return new Promise((resolve, reject) => {
    const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';

    const args = [
      '-m', 'assembly_line.context_service',
      '--project', projectArg,
      '--file', targetFileRel,
    ];

    const env = { ...process.env, PYTHONPATH: path.join(workspaceRoot, 'src') };

    execFile(pythonCmd, args, { cwd: workspaceRoot, env, timeout: 30000 }, (error, stdout, stderr) => {
      if (error) {
        return reject(new Error(`Python error: ${stderr || error.message}`));
      }

      try {
        const data = JSON.parse(stdout);
        resolve(data);
      } catch (parseErr) {
        reject(new Error(`Failed to parse context JSON: ${parseErr.message}\nstdout: ${stdout}`));
      }
    });
  });
}

// ─────────────────────────────────────────────
//  Copilot LM model selection (priority order)
// ─────────────────────────────────────────────

async function getCopilotModel() {
  try {
    // Ưu tiên 1: Claude 3.5 Sonnet
    let models = await vscode.lm.selectChatModels({ vendor: 'copilot', family: 'claude-3.5-sonnet' });
    if (models && models.length > 0) return models[0];

    // Ưu tiên 2: GPT-4o
    models = await vscode.lm.selectChatModels({ vendor: 'copilot', family: 'gpt-4o' });
    if (models && models.length > 0) return models[0];

    // Fallback: Bất kỳ model Copilot nào
    models = await vscode.lm.selectChatModels({ vendor: 'copilot' });
    if (models && models.length > 0) return models[0];
  } catch (e) {
    console.warn('Error selecting Copilot chat model:', e);
  }
  return null;
}

// ─────────────────────────────────────────────
//  Prompt builders
// ─────────────────────────────────────────────

function buildPrompt(targetFile, task, code, optimizedContext) {
  const lines = [
    'You are a senior software engineer.',
    'Return unified diff only.',
    'Do not explain.',
    'Do not modify files outside allowed context.',
    'Do not touch .env, secrets, credentials.',
    '',
    `Target file: ${targetFile}`,
    `Task: ${task}`,
  ];

  if (optimizedContext) {
    lines.push('', 'Related code context (optimized):', optimizedContext);
  }

  lines.push('', 'Current file content:', code);
  return lines.join('\n');
}

function buildRepairPrompt(previousOutput, targetFile) {
  return [
    'Convert the following model output into a valid unified diff patch.',
    'Return unified diff only.',
    'No explanation.',
    `Target file: ${targetFile}`,
    '',
    'Previous output:',
    previousOutput,
  ].join('\n');
}

// ─────────────────────────────────────────────
//  Copilot LM request
// ─────────────────────────────────────────────

async function requestPatchText(model, prompt) {
  const request = await model.sendRequest(
    [vscode.LanguageModelChatMessage.User(prompt)],
    {},
    new vscode.CancellationTokenSource().token
  );

  let text = '';
  for await (const fragment of request.text) {
    text += fragment;
  }

  return text;
}

// ─────────────────────────────────────────────
//  Mock patch generator (fallback khi chưa đăng nhập Copilot)
// ─────────────────────────────────────────────

function generateMockPatch(targetFile, task) {
  if (targetFile.includes('report_service.py')) {
    return `--- a/app/services/report_service.py
+++ b/app/services/report_service.py
@@ -8,8 +8,5 @@
-def export_report(data: list[dict[str, Any]] | None) -> str:
-    """
-    Bug demo:
-    - [] nên trả về "No data to export"
-    - None nên trả về "No data to export"
-    - hiện tại chưa xử lý gì, cứ gọi export_excel
-    """
-    return export_excel(data)
+def export_report(data: list[dict[str, Any]] | None) -> str:
+    if data is None or len(data) == 0:
+        return "No data to export"
+
+    return export_excel(data)
`;
  }

  return `--- a/${targetFile}
+++ b/${targetFile}
@@ -1,1 +1,2 @@
+# Mock patch stub for task: ${task}
`;
}

// ─────────────────────────────────────────────
//  Unified diff parser & applier (in-memory)
// ─────────────────────────────────────────────

function applyUnifiedDiffToText(originalText, patchText, targetFile) {
  const hunks = parseUnifiedDiff(patchText, targetFile);
  if (hunks.length === 0) {
    return originalText;
  }

  const originalLines = originalText.split('\n');
  const resultLines = [];
  let srcIndex = 0;

  for (const hunk of hunks) {
    const hunkStart = Math.max(hunk.srcStart - 1, 0);

    // Copy lines before this hunk
    while (srcIndex < hunkStart && srcIndex < originalLines.length) {
      resultLines.push(originalLines[srcIndex]);
      srcIndex++;
    }

    // Process hunk lines
    for (const line of hunk.lines) {
      if (line.type === 'context') {
        if (srcIndex < originalLines.length) {
          resultLines.push(originalLines[srcIndex]);
          srcIndex++;
        }
      } else if (line.type === 'remove') {
        if (srcIndex < originalLines.length) {
          srcIndex++;
        }
      } else if (line.type === 'add') {
        resultLines.push(line.content);
      }
    }
  }

  // Copy remaining lines
  while (srcIndex < originalLines.length) {
    resultLines.push(originalLines[srcIndex]);
    srcIndex++;
  }

  return resultLines.join('\n');
}

function parseUnifiedDiff(patchText, targetFile) {
  const lines = patchText.split('\n');
  const hunks = [];
  let i = 0;
  let inTargetFile = false;

  while (i < lines.length) {
    const line = lines[i];

    // Detect file header
    if (line.startsWith('--- a/')) {
      const nextLine = lines[i + 1] || '';
      if (nextLine.startsWith('+++ b/')) {
        inTargetFile = true;
        i += 2;
        continue;
      }
    }

    // Parse hunk header
    if (inTargetFile && line.startsWith('@@')) {
      const match = line.match(/^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@/);
      if (match) {
        const srcStart = parseInt(match[1], 10);
        const hunkLines = [];

        i++;
        while (i < lines.length) {
          const hunkLine = lines[i];

          if (hunkLine.startsWith('@@') || hunkLine.startsWith('--- ') || hunkLine.startsWith('+++ ')) {
            break;
          }

          if (hunkLine.startsWith('-')) {
            hunkLines.push({ type: 'remove', content: hunkLine.slice(1) });
          } else if (hunkLine.startsWith('+')) {
            hunkLines.push({ type: 'add', content: hunkLine.slice(1) });
          } else if (hunkLine.startsWith(' ') || hunkLine === '') {
            hunkLines.push({ type: 'context', content: hunkLine.slice(1) });
          } else {
            // End of hunk (new file header or end of patch)
            break;
          }

          i++;
        }

        hunks.push({ srcStart, lines: hunkLines });
        continue;
      }
    }

    i++;
  }

  return hunks;
}

// ─────────────────────────────────────────────
//  Patch output normalizer
// ─────────────────────────────────────────────

function normalizeModelPatchOutput(text) {
  const stripped = stripMarkdownFence(text).trim();

  if (isUnifiedDiffPatch(stripped)) {
    return stripped;
  }

  const fencedBlocks = [...text.matchAll(/```(?:diff|patch)?\s*([\s\S]*?)```/gi)];
  for (const match of fencedBlocks) {
    const candidate = String(match[1] || '').trim();
    if (isUnifiedDiffPatch(candidate)) {
      return candidate;
    }
  }

  const headerIndex = text.search(/^---\s+a\/.+$/m);
  if (headerIndex >= 0) {
    const candidate = text.slice(headerIndex).trim();
    if (isUnifiedDiffPatch(candidate)) {
      return candidate;
    }
  }

  return stripped;
}

function stripMarkdownFence(text) {
  const trimmed = text.trim();
  if (!trimmed.startsWith('```')) {
    return text;
  }

  const lines = trimmed.split(/\r?\n/);
  if (lines.length < 3) {
    return text;
  }

  if (!lines[0].startsWith('```') || lines[lines.length - 1] !== '```') {
    return text;
  }

  return lines.slice(1, -1).join('\n');
}

function isUnifiedDiffPatch(text) {
  const hasOldHeader = /^---\s+a\/.+/m.test(text);
  const hasNewHeader = /^\+\+\+\s+b\/.+/m.test(text);
  const hasHunk = /^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@/m.test(text);

  return hasOldHeader && hasNewHeader && hasHunk;
}

// ─────────────────────────────────────────────
//  Evidence Report writer
// ─────────────────────────────────────────────

async function writeEvidenceReport(workspaceRoot, data) {
  const outputDir = path.join(workspaceRoot, 'outputs');
  await fs.mkdir(outputDir, { recursive: true });

  const now = new Date().toISOString();

  // run_log.json
  const logPayload = {
    generated_at: now,
    task: data.task,
    target_file: data.targetFile,
    related_files: data.relatedFiles,
    token_metrics: data.tokenMetrics,
    patch_text: data.patchText,
    final_status: data.status,
    decision: data.decision,
    llm_backend: data.llmBackend,
    pipeline_mode: 'extension-driven',
  };

  await fs.writeFile(
    path.join(outputDir, 'run_log.json'),
    JSON.stringify(logPayload, null, 2) + '\n',
    'utf-8'
  );

  // patch.diff
  await fs.writeFile(
    path.join(outputDir, 'patch.diff'),
    data.patchText + '\n',
    'utf-8'
  );

  // evidence_report.md
  const relatedMd = data.relatedFiles.map((f) => `- \`${f}\``).join('\n') || '- None';
  const tm = data.tokenMetrics || {};

  const report = `# AI Code Assembly Line - Evidence Report

## Metadata

- Generated at: \`${now}\`
- Pipeline mode: **Extension-Driven**
- Final status: **${(data.status || 'unknown').toUpperCase()}**
- Decision: **${data.decision}**

## User Task

${data.task}

## Target File

\`${data.targetFile}\`

## Related Files Detected

${relatedMd}

## Context Optimization

- Raw context tokens: \`${tm.raw_tokens || 'N/A'}\`
- Optimized context tokens: \`${tm.optimized_tokens || 'N/A'}\`
- Saved tokens: \`${tm.saved_tokens || 'N/A'}\`
- Saved percent: \`${tm.saved_percent || 0}%\`

## LLM Backend

- Backend: \`${data.llmBackend}\`

## Patch

\`\`\`diff
${data.patchText}
\`\`\`
`;

  await fs.writeFile(
    path.join(outputDir, 'evidence_report.md'),
    report,
    'utf-8'
  );
}

// ─────────────────────────────────────────────
//  Show last run summary
// ─────────────────────────────────────────────

async function showRunSummary() {
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) {
    throw new Error('Open a workspace folder first.');
  }

  const workspaceRoot = workspaceFolder.uri.fsPath;
  const logPath = path.join(workspaceRoot, 'outputs', 'run_log.json');

  let raw;
  try {
    raw = await fs.readFile(logPath, 'utf-8');
  } catch (err) {
    throw new Error(`Cannot read run log at outputs/run_log.json: ${String(err)}`);
  }

  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new Error('outputs/run_log.json is not valid JSON.');
  }

  const status = String(data.final_status || data.status || 'unknown').toUpperCase();
  const decision = String(data.decision || 'N/A');
  const target = String(data.target_file || 'N/A');
  const pipelineMode = String(data.pipeline_mode || 'N/A');

  const summaryLine =
    `Status: ${status} | Decision: ${decision} | Target: ${target} | Mode: ${pipelineMode}`;

  if (status === 'APPLIED') {
    void vscode.window.showInformationMessage(summaryLine);
  } else {
    void vscode.window.showWarningMessage(summaryLine);
  }

  const output = vscode.window.createOutputChannel('AI Code Assembly');
  output.clear();
  output.appendLine('AI Code Assembly - Run Summary');
  output.appendLine('='.repeat(48));
  output.appendLine(`Generated at: ${String(data.generated_at || 'N/A')}`);
  output.appendLine(`Status: ${status}`);
  output.appendLine(`Decision: ${decision}`);
  output.appendLine(`Target file: ${target}`);
  output.appendLine(`Pipeline mode: ${pipelineMode}`);
  output.appendLine(`Log path: ${logPath}`);
  output.appendLine('');
  output.show(true);
}

// ─────────────────────────────────────────────
//  Utility functions
// ─────────────────────────────────────────────

function normalizeRel(input) {
  return input.replace(/\\/g, '/').replace(/^\.\//, '');
}

function sanitizeProjectInput(input) {
  return input.trim().replace(/^['"]+|['"]+$/g, '');
}

function detectProjectRootFromActiveFile(workspaceRoot, activeAbs) {
  const rel = path.relative(workspaceRoot, activeAbs);
  if (rel.startsWith('..') || path.isAbsolute(rel)) {
    return '';
  }

  const segments = normalizeRel(rel).split('/').filter(Boolean);
  return segments.length > 1 ? segments[0] : '';
}

function isPathInside(parent, child) {
  const rel = path.relative(parent, child);
  if (rel === '') {
    return true;
  }

  return !rel.startsWith('..') && !path.isAbsolute(rel);
}

module.exports = {
  activate,
  deactivate,
};
