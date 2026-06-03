const fs = require('fs').promises;
const path = require('path');
const vscode = require('vscode');

function activate(context) {
  const safePatchCommand = vscode.commands.registerCommand(
    'aiCodeAssembly.safePatchCurrentFile',
    async () => {
      try {
        await runSafePatchFlow();
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

  context.subscriptions.push(safePatchCommand, showSummaryCommand);
}

function deactivate() {
  // no-op
}

async function runSafePatchFlow() {
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

  const workspaceRelativeProjectAbs = normalizeRel(path.relative(workspaceRoot, projectAbs));
  const projectArg = isPathInside(workspaceRoot, projectAbs)
    ? workspaceRelativeProjectAbs
    : projectAbs;

  const docText = editor.document.getText();

  const models = await vscode.lm.selectChatModels({ vendor: 'copilot' });
  const model = models[0];
  if (!model) {
    throw new Error('No Copilot language model available for this user.');
  }

  const prompt = buildPrompt(targetFileRel, task, docText);
  let patchText = await requestPatchText(model, prompt);
  patchText = normalizeModelPatchOutput(patchText).trim();
  if (!patchText) {
    throw new Error('Model returned empty patch text.');
  }

  if (!isUnifiedDiffPatch(patchText)) {
    const repairPrompt = buildRepairPrompt(patchText, targetFileRel);
    const repairedText = await requestPatchText(model, repairPrompt);
    const repairedPatch = normalizeModelPatchOutput(repairedText).trim();

    if (!isUnifiedDiffPatch(repairedPatch)) {
      const reason =
        'Model output is not a valid unified diff (missing --- a/, +++ b/, @@ headers).';
      throw new Error(`${reason} Patch execution was cancelled.`);
    }

    patchText = repairedPatch;
  }

  const tmpDir = path.join(workspaceRoot, '.tmp');
  const patchFile = path.join(tmpDir, 'copilot_patch.diff');
  await fs.mkdir(tmpDir, { recursive: true });
  await fs.writeFile(patchFile, `${patchText}\n`, 'utf-8');

  const terminal = vscode.window.createTerminal({
    name: 'AI Code Assembly Line',
    cwd: workspaceRoot,
  });

  const cmd =
    "$env:PYTHONPATH='src'; " +
    `python -m assembly_line.main --project \"${escapeForPowerShell(projectArg)}\" --file \"${targetFileRel}\" ` +
    `--task \"${escapeForPowerShell(task)}\" --llm-mode external-patch ` +
    `--patch-file \".tmp/copilot_patch.diff\" --output outputs`;

  terminal.show(true);
  terminal.sendText(cmd, true);

  void vscode.window.showInformationMessage(
    'Copilot patch generated and pipeline started in terminal.'
  );
}

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

  const status = String(data.final_status || 'unknown').toUpperCase();
  const decision = String(data.decision || data.final_decision || 'N/A');
  const attempts = data.attempts_used ?? 'N/A';
  const maxAttempts = data.max_attempts ?? 'N/A';
  const changed = Array.isArray(data.changed_files) ? data.changed_files.length : 0;
  const target = String(data.target_file || 'N/A');

  const summaryLine =
    `Status: ${status} | Decision: ${decision} | Attempts: ${attempts}/${maxAttempts} | Changed files: ${changed}`;

  if (status === 'PASSED') {
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
  output.appendLine(`Attempts: ${attempts}/${maxAttempts}`);
  output.appendLine(`Changed files: ${changed}`);
  output.appendLine(`Log path: ${logPath}`);
  output.appendLine('');

  const errors = Array.isArray(data.last_error_summary) ? data.last_error_summary : [];
  if (errors.length) {
    output.appendLine('Last error summary:');
    for (const line of errors) {
      output.appendLine(`- ${line}`);
    }
  } else {
    output.appendLine('Last error summary: none');
  }

  output.show(true);
}

function buildPrompt(targetFile, task, code) {
  return [
    'Return unified diff only.',
    'Do not explain.',
    'Do not modify files outside allowed context.',
    'Do not touch .env, secrets, credentials.',
    '',
    `Target file: ${targetFile}`,
    `Task: ${task}`,
    '',
    'Current file content:',
    code,
  ].join('\n');
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

function normalizeModelPatchOutput(text) {
  const stripped = stripMarkdownFence(text).trim();

  // If the whole output is a pure fenced diff, use it directly.
  if (isUnifiedDiffPatch(stripped)) {
    return stripped;
  }

  // Try extracting fenced blocks when model adds explanations around the patch.
  const fencedBlocks = [...text.matchAll(/```(?:diff|patch)?\s*([\s\S]*?)```/gi)];
  for (const match of fencedBlocks) {
    const candidate = String(match[1] || '').trim();
    if (isUnifiedDiffPatch(candidate)) {
      return candidate;
    }
  }

  // Try extracting from the first unified diff file header.
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

function isUnifiedDiffPatch(text) {
  const hasOldHeader = /^---\s+a\/.+/m.test(text);
  const hasNewHeader = /^\+\+\+\s+b\/.+/m.test(text);
  const hasHunk = /^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@/m.test(text);

  return hasOldHeader && hasNewHeader && hasHunk;
}

function escapeForPowerShell(input) {
  return input.replace(/`/g, '``').replace(/"/g, '`"');
}

module.exports = {
  activate,
  deactivate,
};
