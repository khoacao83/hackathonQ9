const vscode = require('vscode');
const http = require('http');
const path = require('path');
const fs = require('fs');
const childProcess = require('child_process');

let server;
let globalSidebarProvider = undefined;

function readJsonSafe(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      return undefined;
    }
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (_) {
    return undefined;
  }
}

function writePrecheckFailureArtifacts(outputDir, task, targetFile, reason) {
  try {
    fs.mkdirSync(outputDir, { recursive: true });
    const timestamp = new Date().toISOString();
    const runLog = {
      timestamp,
      task,
      target_file: targetFile,
      decision: 'NEED_DEVELOPER_REVIEW',
      stage: 'PRECHECK',
      attempts: 0,
      token_stats: {
        raw_tokens: 0,
        opt_tokens: 0,
        saving_pct: 0,
      },
      changed_files: [],
      error: reason,
    };

    fs.writeFileSync(path.join(outputDir, 'run_log.json'), JSON.stringify(runLog, null, 2), 'utf8');

    const evidence = [
      '# AI Code Assembly Line — Evidence Report',
      '',
      `**Generated**: ${timestamp}`,
      `**Task**: ${task}`,
      `**Target file**: ${targetFile}`,
      '**Decision**: NEED_DEVELOPER_REVIEW',
      '',
      '## Failure Stage',
      '- PRECHECK',
      '',
      '## Error',
      '```',
      reason,
      '```',
    ].join('\n');
    fs.writeFileSync(path.join(outputDir, 'evidence_report.md'), evidence, 'utf8');
  } catch (_) {
    // Best-effort only: do not mask the original precheck failure.
  }
}

async function runPrecheckGate({ workspaceRoot, projectRoot, assemblyLineRoot, proxyClientPath, config }) {
  if (!workspaceRoot) {
    return { ok: false, reason: 'Precheck failed: workspace is not open.' };
  }
  if (!fs.existsSync(projectRoot)) {
    return { ok: false, reason: `Precheck failed: project root not found: ${projectRoot}` };
  }
  if (!fs.existsSync(assemblyLineRoot)) {
    return { ok: false, reason: `Precheck failed: assembly line root not found: ${assemblyLineRoot}` };
  }
  if (!fs.existsSync(proxyClientPath)) {
    return { ok: false, reason: `Precheck failed: proxy client not found: ${proxyClientPath}` };
  }

  const targetEditor = vscode.window.activeTextEditor;
  if (!targetEditor) {
    return { ok: false, reason: 'Precheck failed: no active editor.' };
  }
  const activeFsPath = targetEditor.document.uri.fsPath;
  if (!activeFsPath.startsWith(projectRoot)) {
    return { ok: false, reason: 'Precheck failed: active file is outside project root.' };
  }

  const pythonVersion = await new Promise(resolve => {
    const child = childProcess.spawn(config.pythonCommand, ['--version'], { shell: false });
    let output = '';
    child.stdout.on('data', d => (output += d.toString()));
    child.stderr.on('data', d => (output += d.toString()));
    child.on('error', err => resolve({ ok: false, reason: `Precheck failed: python command error: ${err}` }));
    child.on('close', code => {
      if (code === 0) {
        resolve({ ok: true, info: output.trim() });
      } else {
        resolve({ ok: false, reason: `Precheck failed: python command returned code ${code}.` });
      }
    });
  });
  if (!pythonVersion.ok) {
    return pythonVersion;
  }

  await startServer();
  const health = await new Promise(resolve => {
    const req = http.get(`http://${config.host}:${config.port}/health`, res => {
      let body = '';
      res.on('data', chunk => (body += chunk.toString()));
      res.on('end', () => {
        if (res.statusCode === 200 && body.includes('ok')) {
          resolve({ ok: true });
        } else {
          resolve({ ok: false, reason: `Precheck failed: bridge health returned ${res.statusCode}.` });
        }
      });
    });
    req.on('error', err => resolve({ ok: false, reason: `Precheck failed: bridge not reachable (${err.message}).` }));
    req.setTimeout(2000, () => {
      req.destroy();
      resolve({ ok: false, reason: 'Precheck failed: bridge health check timeout.' });
    });
  });
  if (!health.ok) {
    return health;
  }

  return { ok: true, reason: `Precheck passed (${pythonVersion.info || 'python ok'})` };
}

function extractUnifiedDiff(text) {
  const raw = String(text || '').trim();
  if (!raw) {
    return '';
  }

  const fenced = raw.match(/```(?:diff)?\s*([\s\S]*?)```/i);
  const candidate = fenced ? fenced[1].trim() : raw;
  if (candidate.includes('--- ') && candidate.includes('+++ ')) {
    return candidate;
  }
  return raw;
}

function createPipelineEnv(config, assemblyLineRoot, proxyClientPath) {
  const env = {
    ...process.env,
    LLM_BACKEND: 'proxy_command',
    LLM_PROXY_COMMAND: `${config.pythonCommand} "${proxyClientPath}"`,
    LM_BRIDGE_URL: `http://${config.host}:${config.port}/patch`,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    USE_DOCKER: '0',
  };
  if (config.setPythonPath) {
    const sourceRoot = path.join(assemblyLineRoot, 'src');
    if (fs.existsSync(sourceRoot)) {
      env.PYTHONPATH = sourceRoot;
    }
  }
  return env;
}

function spawnPipeline(channel, config, assemblyLineRoot, env, args, onData) {
  return new Promise(resolve => {
    const startMsg = `[pipeline] ${config.pythonCommand} ${args.join(' ')}`;
    channel.appendLine(startMsg);
    if (onData) { onData(startMsg + '\n'); }

    const child = childProcess.spawn(config.pythonCommand, args, {
      cwd: assemblyLineRoot,
      env,
      shell: false,
    });

    child.stdout.on('data', data => {
      const txt = data.toString();
      channel.append(txt);
      if (onData) { onData(txt); }
    });
    child.stderr.on('data', data => {
      const txt = data.toString();
      channel.append(txt);
      if (onData) { onData(txt); }
    });
    child.on('close', code => resolve(code ?? 1));
  });
}

function getTokenSavingFromItem(item) {
  const tokens = item && item.tokens;
  if (!tokens || typeof tokens.saving_pct === 'undefined') {
    return undefined;
  }
  return tokens.saving_pct;
}

function collectBatchReviewItems(summary) {
  const results = summary && Array.isArray(summary.results) ? summary.results : [];
  return results.filter(item => {
    if (!item || item.decision !== 'READY_FOR_HUMAN_REVIEW') {
      return false;
    }
    if (!item.patch_file || typeof item.patch_file !== 'string') {
      return false;
    }
    return fs.existsSync(item.patch_file);
  });
}

async function reviewAutoDetectBatch({ channel, config, assemblyLineRoot, env, projectRoot, outputDir, summaryPath }) {
  const summary = readJsonSafe(summaryPath);
  if (!summary) {
    channel.appendLine('[review] auto_fix_summary.json not found; skipping batch review.');
    return { reviewed: 0, accepted: 0, rejected: 0, failed: 0 };
  }

  const pending = collectBatchReviewItems(summary);
  if (!pending.length) {
    channel.appendLine('[review] no READY_FOR_HUMAN_REVIEW items found in auto-fix summary.');
    return { reviewed: 0, accepted: 0, rejected: 0, failed: 0 };
  }

  channel.appendLine(`[review] ${pending.length} item(s) ready for per-file approval.`);

  let accepted = 0;
  let rejected = 0;
  let failed = 0;
  let reviewed = 0;

  while (pending.length) {
    const picks = pending.map(item => {
      const savingPct = getTokenSavingFromItem(item);
      return {
        label: item.file || 'unknown file',
        description: typeof savingPct !== 'undefined' ? `Token saving: ${savingPct}%` : 'Token saving: n/a',
        detail: item.task || 'Validated patch ready',
        item,
      };
    });
    picks.push({
      label: 'Finish Review',
      description: 'Stop reviewing now',
      detail: 'You can rerun auto-detect later to review remaining items.',
      item: undefined,
    });

    const picked = await vscode.window.showQuickPick(picks, {
      title: 'Auto-Detect Review: choose a validated patch',
      placeHolder: 'Select a file to review and accept/reject',
      ignoreFocusOut: true,
    });

    if (!picked || !picked.item) {
      break;
    }

    const current = picked.item;
    reviewed += 1;

    try {
      const patchDoc = await vscode.workspace.openTextDocument(vscode.Uri.file(current.patch_file));
      await vscode.window.showTextDocument(patchDoc, { preview: false, preserveFocus: true });
      channel.appendLine(`[review] opened ${current.patch_file}`);
    } catch (err) {
      channel.appendLine(`[review] could not open patch file: ${err instanceof Error ? err.message : String(err)}`);
    }

    const consent = await vscode.window.showInformationMessage(
      `Apply validated patch for ${current.file}?`,
      { modal: true },
      'Accept',
      'Reject'
    );

    const idx = pending.indexOf(current);
    if (idx >= 0) {
      pending.splice(idx, 1);
    }

    if (consent !== 'Accept') {
      rejected += 1;
      channel.appendLine(`[review] rejected ${current.file}`);
      continue;
    }

    const args = [
      '-m', 'assembly_line.main',
      '--project', projectRoot,
      '--file', current.file,
      '--task', current.task || `Apply validated patch for ${current.file}`,
      '--llm-mode', 'external-patch',
      '--patch-file', current.patch_file,
      '--output', outputDir,
      '--apply-source',
    ];

    const applyCode = await spawnPipeline(channel, config, assemblyLineRoot, env, args, (data) => {
      if (globalSidebarProvider) {
        globalSidebarProvider.appendLog(data);
      }
    });
    if (applyCode === 0) {
      accepted += 1;
      channel.appendLine(`[review] accepted and applied ${current.file}`);
    } else {
      failed += 1;
      channel.appendLine(`[review] apply failed for ${current.file} (code ${applyCode})`);
    }
  }

  return { reviewed, accepted, rejected, failed };
}

function getConfig() {
  const cfg = vscode.workspace.getConfiguration('copilotLmBridge');
  const legacyProjectRoot = cfg.get('workspaceProjectRoot', '').trim();
  return {
    host: cfg.get('host', '127.0.0.1'),
    port: cfg.get('port', 8765),
    family: cfg.get('family', 'gpt-4o'),
    autoStart: cfg.get('autoStart', true),
    projectRoot: cfg.get('projectRoot', legacyProjectRoot || '.'),
    assemblyLineRoot: cfg.get('assemblyLineRoot', ''),
    outputDir: cfg.get('outputDir', 'outputs'),
    proxyClientPath: cfg.get('proxyClientPath', 'tools/lm_proxy_http_client.py'),
    setPythonPath: cfg.get('setPythonPath', true),
    pythonCommand: cfg.get('pythonCommand', 'python'),
  };
}

function getWorkspaceRoot() {
  const folder = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
  return folder ? folder.uri.fsPath : undefined;
}

function normalizeToPosix(relPath) {
  return relPath.split(path.sep).join('/');
}

function resolveConfigPath(basePath, configuredPath) {
  if (!configuredPath || !configuredPath.trim()) {
    return basePath;
  }
  if (path.isAbsolute(configuredPath)) {
    return configuredPath;
  }
  return path.resolve(basePath, configuredPath);
}

function resolveProxyClientPath(assemblyLineRoot, configuredProxyClientPath) {
  let configured = configuredProxyClientPath;
  if (configured && configured.startsWith('file://')) {
    try {
      const url = new URL(configured);
      configured = decodeURIComponent(url.pathname);
      if (/^\/[A-Za-z]:\//.test(configured)) {
        configured = configured.slice(1);
      }
      configured = configured.replace(/\//g, path.sep);
    } catch (_) {
      configured = configuredProxyClientPath;
    }
  }

  const candidates = [];
  if (configured && configured.trim()) {
    if (path.isAbsolute(configured)) {
      candidates.push(configured);
    } else {
      candidates.push(path.resolve(assemblyLineRoot, configured));
      candidates.push(path.resolve(assemblyLineRoot, 'tools', configured));
    }
  }

  candidates.push(path.resolve(assemblyLineRoot, 'tools', 'lm_proxy_http_client.py'));

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return candidates[0];
}

function resolveTargetFileFromActiveEditor(projectRootPath) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return undefined;
  }

  const filePath = editor.document.uri.fsPath;
  if (!filePath.startsWith(projectRootPath)) {
    return undefined;
  }

  return normalizeToPosix(path.relative(projectRootPath, filePath));
}

async function runPipelineFixCommand(inputTask) {
  const workspaceRoot = getWorkspaceRoot();
  if (!workspaceRoot) {
    vscode.window.showErrorMessage('Copilot LM Bridge: open a workspace folder first.');
    return;
  }

  const config = getConfig();
  const projectRoot = resolveConfigPath(workspaceRoot, config.projectRoot);
  const assemblyLineRoot = resolveConfigPath(workspaceRoot, config.assemblyLineRoot);
  const proxyClientPath = resolveProxyClientPath(assemblyLineRoot, config.proxyClientPath);

  if (!fs.existsSync(projectRoot)) {
    vscode.window.showErrorMessage(`Copilot LM Bridge: project root not found: ${projectRoot}`);
    return;
  }

  if (!fs.existsSync(proxyClientPath)) {
    vscode.window.showErrorMessage(`Copilot LM Bridge: proxy client not found: ${proxyClientPath}`);
    return;
  }

  const targetFile = resolveTargetFileFromActiveEditor(projectRoot)
    || await vscode.window.showInputBox({
      prompt: 'Target file path relative to project root',
      placeHolder: 'src/module/file.py',
      ignoreFocusOut: true,
    });

  if (!targetFile) {
    return;
  }

  const task = inputTask || await vscode.window.showInputBox({
    prompt: 'Describe the fix task',
    placeHolder: 'Fix payment transfer when balance cannot cover amount plus fee',
    ignoreFocusOut: true,
  });

  if (!task) {
    return;
  }

  if (globalSidebarProvider) {
    globalSidebarProvider.clearLog();
    globalSidebarProvider.appendLog(`[Assembly Line] Bắt đầu sửa file: ${targetFile}\n`);
    globalSidebarProvider.appendLog(`[Assembly Line] Yêu cầu: "${task}"\n\n`);
  }

  const channel = vscode.window.createOutputChannel('AI Code Assembly Line');
  channel.show(true);

  const outputDir = path.isAbsolute(config.outputDir)
    ? config.outputDir
    : path.resolve(projectRoot, config.outputDir);

  const precheck = await runPrecheckGate({
    workspaceRoot,
    projectRoot,
    assemblyLineRoot,
    proxyClientPath,
    config,
  });
  channel.appendLine(`[precheck] ${precheck.reason}`);
  if (globalSidebarProvider) {
    globalSidebarProvider.appendLog(`[Precheck] ${precheck.reason}\n`);
  }

  if (!precheck.ok) {
    writePrecheckFailureArtifacts(outputDir, task, targetFile, precheck.reason);
    vscode.window.showWarningMessage(precheck.reason);
    return;
  }

  const env = createPipelineEnv(config, assemblyLineRoot, proxyClientPath);

  const targetAbsPath = path.resolve(projectRoot, targetFile);
  let targetSnippet = '';
  try {
    if (fs.existsSync(targetAbsPath)) {
      targetSnippet = fs.readFileSync(targetAbsPath, 'utf8');
    }
  } catch (_) {
    targetSnippet = '';
  }

  const generationPrompt = [
    'Generate a unified diff patch only.',
    `Task: ${task}`,
    `Target file: ${targetFile}`,
    'Constraints:',
    '- Output only unified diff text (no markdown fences, no explanation).',
    '- Modify only project files relevant to the task.',
    '- Keep patch minimal and test-focused.',
    '',
    'Current target file content:',
    targetSnippet,
  ].join('\n');

  let modelPatch = '';
  try {
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(`[LLM] Đang yêu cầu sinh bản vá từ Copilot Language Model...\n`);
    }
    const lmResult = await runModelRequest({
      task,
      target_file: targetFile,
      context: targetSnippet,
      prompt: generationPrompt,
    });
    modelPatch = extractUnifiedDiff(lmResult);
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(`[LLM] Nhận bản vá thành công.\n`);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`Copilot LM Bridge patch generation failed: ${message}`);
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(`[LỖI] Sinh bản vá thất bại: ${message}\n`);
    }
    return;
  }

  if (!modelPatch || !modelPatch.trim()) {
    vscode.window.showErrorMessage('Copilot LM Bridge: model returned empty patch.');
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(`[LỖI] Model trả về bản vá rỗng.\n`);
    }
    return;
  }

  const tmpDir = path.join(projectRoot, '.tmp');
  fs.mkdirSync(tmpDir, { recursive: true });
  const patchFile = path.join(tmpDir, 'copilot_patch.diff');
  fs.writeFileSync(patchFile, modelPatch, 'utf8');

  const baseArgs = [
    '-m', 'assembly_line.main',
    '--project', projectRoot,
    '--file', targetFile,
    '--task', task,
    '--llm-mode', 'external-patch',
    '--patch-file', patchFile,
    '--output', outputDir,
  ];

  channel.appendLine(`[pipeline] engine_root=${assemblyLineRoot}`);
  channel.appendLine(`[pipeline] project_root=${projectRoot}`);
  channel.appendLine(`[pipeline] saved generated patch -> ${patchFile}`);

  if (globalSidebarProvider) {
    globalSidebarProvider.appendLog(`[Pipeline] Chạy lệnh python: ${config.pythonCommand} ${baseArgs.join(' ')}\n`);
  }

  const validateCode = await spawnPipeline(channel, config, assemblyLineRoot, env, baseArgs, (data) => {
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(data);
    }
  });
  channel.appendLine(`\n[pipeline] validate process exited with code ${validateCode}`);

  const runLogPath = path.join(outputDir, 'run_log.json');
  const runLog = readJsonSafe(runLogPath) || {};
  const decision = String(runLog.decision || 'UNKNOWN');
  const savingPct = runLog.token_stats && typeof runLog.token_stats.saving_pct !== 'undefined'
    ? runLog.token_stats.saving_pct
    : undefined;

  if (typeof savingPct !== 'undefined') {
    channel.appendLine(`[pipeline] token saving: ${savingPct}%`);
  }

  if (decision !== 'READY_FOR_HUMAN_REVIEW') {
    vscode.window.showWarningMessage(
      `AI Code Assembly Line finished with decision ${decision}.${typeof savingPct !== 'undefined' ? ` Token saving: ${savingPct}%` : ''}`
    );
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(`\n[Kết quả] Kiểm thử thất bại. Quyết định: ${decision}\n`);
    }
    return;
  }

  const patchDiffPath = path.join(outputDir, 'patch.diff');
  if (fs.existsSync(patchDiffPath)) {
    try {
      const patchDoc = await vscode.workspace.openTextDocument(vscode.Uri.file(patchDiffPath));
      await vscode.window.showTextDocument(patchDoc, { preview: false, preserveFocus: true });
      channel.appendLine(`[review] opened validated patch: ${patchDiffPath}`);
    } catch (err) {
      channel.appendLine(`[review] could not open patch diff: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  let consent;
  if (globalSidebarProvider) {
    globalSidebarProvider.appendLog(`\n[Chờ Duyệt] Bản vá kiểm định xong. Đang chờ bạn phê duyệt...\n`);
    consent = await new Promise((resolve) => {
      globalSidebarProvider.showReview(targetFile, savingPct || 'n/a', (decision) => {
        resolve(decision);
      });
      // Also show standard information message
      vscode.window.showInformationMessage(
        `Validated patch is ready. Review patch.diff, then choose Accept or Reject.${typeof savingPct !== 'undefined' ? ` (Token saving: ${savingPct}%)` : ''}`,
        { modal: true },
        'Accept',
        'Reject'
      ).then(res => {
        if (res) resolve(res);
      });
    });
    globalSidebarProvider.hideReview();
  } else {
    consent = await vscode.window.showInformationMessage(
      `Validated patch is ready. Review patch.diff, then choose Accept or Reject.${typeof savingPct !== 'undefined' ? ` (Token saving: ${savingPct}%)` : ''}`,
      { modal: true },
      'Accept',
      'Reject'
    );
  }

  if (consent !== 'Accept') {
    channel.appendLine('[pipeline] user rejected source apply.');
    vscode.window.showInformationMessage('Patch validation completed. Source file unchanged.');
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(`[Từ Chối] Người dùng từ chối áp dụng bản vá.\n`);
    }
    return;
  }

  if (globalSidebarProvider) {
    globalSidebarProvider.appendLog(`[Áp Dụng] Đang áp dụng bản vá vào mã nguồn gốc...\n`);
  }

  const applyCode = await spawnPipeline(channel, config, assemblyLineRoot, env, [...baseArgs, '--apply-source'], (data) => {
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(data);
    }
  });
  channel.appendLine(`\n[pipeline] apply process exited with code ${applyCode}`);
  if (applyCode === 0) {
    vscode.window.showInformationMessage('Patch applied to source after user approval.');
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(`[Hoàn Thành] Bản vá đã được áp dụng thành công!\n`);
    }
  } else {
    vscode.window.showErrorMessage(`Validated apply step failed (code ${applyCode}).`);
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(`[LỖI] Áp dụng bản vá thất bại với code: ${applyCode}\n`);
    }
  }
}

async function runAutoDetectFixCommand() {
  const workspaceRoot = getWorkspaceRoot();
  if (!workspaceRoot) {
    vscode.window.showErrorMessage('Copilot LM Bridge: open a workspace folder first.');
    return;
  }

  const config = getConfig();
  const projectRoot = resolveConfigPath(workspaceRoot, config.projectRoot);
  const assemblyLineRoot = resolveConfigPath(workspaceRoot, config.assemblyLineRoot);
  const proxyClientPath = resolveProxyClientPath(assemblyLineRoot, config.proxyClientPath);

  if (!fs.existsSync(projectRoot)) {
    vscode.window.showErrorMessage(`Copilot LM Bridge: project root not found: ${projectRoot}`);
    return;
  }

  const autoFixScriptPath = path.resolve(assemblyLineRoot, 'tools', 'auto_fix_project.py');
  if (!fs.existsSync(autoFixScriptPath)) {
    vscode.window.showErrorMessage(`Copilot LM Bridge: auto-fix script not found: ${autoFixScriptPath}`);
    return;
  }

  await startServer();

  if (globalSidebarProvider) {
    globalSidebarProvider.clearLog();
    globalSidebarProvider.appendLog(`[Auto-Detect] Khởi động chế độ quét và tự động sửa lỗi toàn bộ dự án...\n`);
  }

  const channel = vscode.window.createOutputChannel('AI Code Assembly Line - Auto-Fix');
  channel.show(true);

  const env = {
    ...process.env,
    LLM_BACKEND: 'proxy_command',
    LLM_PROXY_COMMAND: `${config.pythonCommand} "${proxyClientPath}"`,
    LM_BRIDGE_URL: `http://${config.host}:${config.port}/patch`,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    USE_DOCKER: '0',
  };
  if (config.setPythonPath) {
    const sourceRoot = path.join(assemblyLineRoot, 'src');
    if (fs.existsSync(sourceRoot)) {
      env.PYTHONPATH = sourceRoot;
    }
  }

  const outputDir = path.isAbsolute(config.outputDir)
    ? config.outputDir
    : path.resolve(projectRoot, config.outputDir);

  const args = [
    autoFixScriptPath,
    '--project', projectRoot,
    '--output', outputDir,
  ];

  channel.appendLine(`[auto-detect] engine_root=${assemblyLineRoot}`);
  channel.appendLine(`[auto-detect] project_root=${projectRoot}`);
  channel.appendLine('[auto-detect] direct apply mode enabled: passing fixes are written to source files.');
  channel.appendLine('[auto-detect] local runner only (USE_DOCKER=0).');
  channel.appendLine(`[auto-detect] Starting auto-detect and fix...\n`);

  if (globalSidebarProvider) {
    globalSidebarProvider.appendLog(`[Auto-Detect] Chạy lệnh: ${config.pythonCommand} ${args.join(' ')}\n\n`);
  }

  const child = childProcess.spawn(config.pythonCommand, args, {
    cwd: assemblyLineRoot,
    env,
    shell: false,
  });

  child.stdout.on('data', data => {
    channel.append(data.toString());
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(data.toString());
    }
  });
  child.stderr.on('data', data => {
    channel.append(data.toString());
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(data.toString());
    }
  });

  child.on('close', async code => {
    channel.appendLine(`\n[auto-detect] process exited with code ${code}`);
    if (globalSidebarProvider) {
      globalSidebarProvider.appendLog(`\n[Auto-Detect] Quá trình quét hoàn tất với code: ${code}\n`);
    }

    const summaryPath = path.join(outputDir, 'auto_fix_summary.json');
    const review = await reviewAutoDetectBatch({
      channel,
      config,
      assemblyLineRoot,
      env,
      projectRoot,
      outputDir,
      summaryPath,
    });

    const reviewSummary = `Reviewed: ${review.reviewed}, Accepted: ${review.accepted}, Rejected: ${review.rejected}, Failed apply: ${review.failed}.`;
    if (code === 0) {
      vscode.window.showInformationMessage(`AI Code Assembly Line auto-fix completed. ${reviewSummary}`);
    } else {
      vscode.window.showWarningMessage(`AI Code Assembly Line auto-fix finished with issues (code ${code}). ${reviewSummary} Check output for details.`);
    }
  });
}

function parseJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', chunk => chunks.push(chunk));
    req.on('end', () => {
      try {
        const raw = Buffer.concat(chunks).toString('utf8') || '{}';
        resolve(JSON.parse(raw));
      } catch (err) {
        reject(err);
      }
    });
    req.on('error', reject);
  });
}

async function selectModel() {
  const { family } = getConfig();
  let models = [];

  try {
    models = await vscode.lm.selectChatModels({ vendor: 'copilot', family });
  } catch (_) {
    models = [];
  }

  if (!models.length) {
    models = await vscode.lm.selectChatModels({ vendor: 'copilot' });
  }

  if (!models.length) {
    throw new Error('No Copilot language model available. Open chat and grant consent first.');
  }

  return models[0];
}

async function runModelRequest(payload) {
  const model = await selectModel();
  const prompt = typeof payload.prompt === 'string' && payload.prompt.trim()
    ? payload.prompt
    : `Task: ${payload.task || ''}\n\nTarget: ${payload.target_file || ''}\n\n${payload.context || ''}`;

  const messages = [vscode.LanguageModelChatMessage.User(prompt)];
  const cancellation = new vscode.CancellationTokenSource();
  const response = await model.sendRequest(messages, {}, cancellation.token);

  let text = '';
  for await (const fragment of response.text) {
    text += fragment;
  }

  if (!text.trim()) {
    throw new Error('Language model returned empty response.');
  }

  return text.trim();
}

function writeJson(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(body));
}

async function startServer() {
  if (server) {
    return;
  }

  const { host, port } = getConfig();

  server = http.createServer(async (req, res) => {
    if (req.method === 'GET' && req.url === '/health') {
      return writeJson(res, 200, { ok: true });
    }

    if (req.method !== 'POST' || req.url !== '/patch') {
      return writeJson(res, 404, { error: 'Not found' });
    }

    try {
      const payload = await parseJsonBody(req);
      const patch = await runModelRequest(payload);
      return writeJson(res, 200, { patch });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return writeJson(res, 500, { error: message });
    }
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => resolve(undefined));
  });

  vscode.window.setStatusBarMessage(`Copilot LM Bridge listening on http://${host}:${port}`, 5000);
}

async function stopServer() {
  if (!server) {
    return;
  }

  const closing = server;
  server = undefined;

  await new Promise((resolve, reject) => {
    closing.close(err => (err ? reject(err) : resolve(undefined)));
  });
}

async function requestConsent() {
  try {
    await selectModel();
    vscode.window.showInformationMessage('Copilot model is available for Copilot LM Bridge.');
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    vscode.window.showWarningMessage(`Copilot LM Bridge: ${message}`);
  }
}

// ── Webview Sidebar Provider Implementation (Minimal Native Style) ───────
class SidebarProvider {
  constructor(context) {
    this.context = context;
    this._view = undefined;
    this._onReviewDecision = undefined;
  }

  resolveWebviewView(webviewView, context, token) {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.context.extensionUri]
    };

    webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

    webviewView.webview.onDidReceiveMessage(async (data) => {
      switch (data.type) {
        case 'startServer':
          try {
            await startServer();
            vscode.window.showInformationMessage('Copilot LM Bridge server started.');
          } catch (err) {
            vscode.window.showErrorMessage(`Failed to start server: ${err.message}`);
          }
          this.updateState();
          break;
        case 'stopServer':
          try {
            await stopServer();
            vscode.window.showInformationMessage('Copilot LM Bridge server stopped.');
          } catch (err) {
            vscode.window.showErrorMessage(`Failed to stop server: ${err.message}`);
          }
          this.updateState();
          break;
        case 'runFix':
          runPipelineFixCommand(data.task);
          break;
        case 'runAutoDetect':
          runAutoDetectFixCommand();
          break;
        case 'acceptPatch':
          if (this._onReviewDecision) {
            this._onReviewDecision('Accept');
          }
          break;
        case 'rejectPatch':
          if (this._onReviewDecision) {
            this._onReviewDecision('Reject');
          }
          break;
        case 'clearConsole':
          this.clearLog();
          break;
        case 'refreshState':
          this.updateState();
          break;
      }
    });

    this.updateState();
  }

  updateState() {
    if (!this._view) return;
    const config = getConfig();
    const workspaceRoot = getWorkspaceRoot() || '';
    const projectRoot = resolveConfigPath(workspaceRoot, config.projectRoot);
    const activeFile = resolveTargetFileFromActiveEditor(projectRoot) || '';

    childProcess.exec(`"${config.pythonCommand}" --version`, (err, stdout, stderr) => {
      let ver = (stdout || stderr || '').trim();
      if (err) {
        ver = "Không khả dụng";
      }
      if (this._view) {
        this._view.webview.postMessage({
          type: 'state',
          serverRunning: !!server,
          host: config.host,
          port: config.port,
          activeFile: activeFile,
          pythonVersion: ver
        });
      }
    });
  }

  appendLog(text) {
    if (this._view) {
      this._view.webview.postMessage({ type: 'log', text });
    }
  }

  clearLog() {
    if (this._view) {
      this._view.webview.postMessage({ type: 'clearLog' });
    }
  }

  showReview(file, saving, onDecision) {
    this._onReviewDecision = onDecision;
    if (this._view) {
      this._view.webview.postMessage({
        type: 'pendingReview',
        visible: true,
        file,
        saving
      });
    }
  }

  hideReview() {
    this._onReviewDecision = undefined;
    if (this._view) {
      this._view.webview.postMessage({
        type: 'pendingReview',
        visible: false
      });
    }
  }

  _getHtmlForWebview(webview) {
    return `<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {
      padding: 12px;
      color: var(--vscode-foreground);
      font-family: var(--vscode-font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
      font-size: var(--vscode-font-size, 13px);
      background-color: var(--vscode-sideBar-background);
      margin: 0;
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      height: 100vh;
    }
    
    /* Top minimal status bar */
    .status-container {
      font-size: 11px;
      color: var(--vscode-descriptionForeground);
      margin-bottom: 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--vscode-panel-border, rgba(255, 255, 255, 0.08));
      padding-bottom: 6px;
    }
    .status-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 4px;
    }
    .status-dot.active {
      background-color: #2ecc71;
    }
    .status-dot.inactive {
      background-color: #e74c3c;
    }

    /* Main output log area (looks like chat bubbles / clean thread) */
    .thread-area {
      flex: 1;
      overflow-y: auto;
      margin-bottom: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding-right: 2px;
    }
    .log-entry {
      font-size: 12px;
      line-height: 1.4;
      color: var(--vscode-foreground);
      background-color: var(--vscode-textBlockQuote-background, rgba(255,255,255,0.02));
      border-left: 2px solid var(--vscode-textBlockQuote-border, rgba(255,255,255,0.1));
      padding: 6px 10px;
      border-radius: 0 6px 6px 0;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .log-system {
      color: var(--vscode-descriptionForeground);
      font-size: 11px;
      font-style: italic;
    }

    /* Approval Section (clean card) */
    .approval-container {
      background-color: var(--vscode-editor-background);
      border: 1px solid var(--vscode-panel-border, rgba(255, 255, 255, 0.1));
      border-radius: 8px;
      padding: 10px;
      margin-bottom: 10px;
    }
    .approval-title {
      font-weight: bold;
      font-size: 12px;
      margin-bottom: 4px;
      color: #2ecc71;
    }
    .approval-desc {
      font-size: 11px;
      color: var(--vscode-descriptionForeground);
      margin-bottom: 8px;
    }
    .approval-buttons {
      display: flex;
      gap: 8px;
    }
    .btn-approve {
      flex: 1;
      background-color: var(--vscode-button-background, #007acc);
      color: var(--vscode-button-foreground, #fff);
      border: none;
      border-radius: 4px;
      padding: 6px;
      font-size: 11px;
      font-weight: bold;
      cursor: pointer;
    }
    .btn-approve:hover {
      background-color: var(--vscode-button-hoverBackground, #0062a3);
    }
    .btn-reject {
      flex: 1;
      background-color: var(--vscode-button-secondaryBackground, rgba(255,255,255,0.1));
      color: var(--vscode-button-secondaryForeground, #ccc);
      border: none;
      border-radius: 4px;
      padding: 6px;
      font-size: 11px;
      cursor: pointer;
    }
    .btn-reject:hover {
      background-color: rgba(255,255,255,0.15);
    }

    /* Input area at the bottom - styled exactly like the Gemini chat box */
    .input-container {
      background-color: var(--vscode-input-background, rgba(0, 0, 0, 0.2));
      border: 1px solid var(--vscode-input-border, rgba(255, 255, 255, 0.15));
      border-radius: 8px;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .input-container:focus-within {
      border-color: var(--vscode-focusBorder, #007acc);
      outline: none;
    }
    .target-file-indicator {
      font-size: 10px;
      color: var(--vscode-descriptionForeground);
      text-overflow: ellipsis;
      overflow: hidden;
      white-space: nowrap;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      padding-bottom: 4px;
    }
    textarea {
      background: transparent;
      border: none;
      color: var(--vscode-input-foreground, #fff);
      font-family: inherit;
      font-size: 12px;
      resize: none;
      width: 100%;
      height: 48px;
      outline: none;
      box-sizing: border-box;
      padding: 0;
    }
    textarea::placeholder {
      color: var(--vscode-input-placeholderForeground, rgba(255, 255, 255, 0.35));
    }
    .input-actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .action-left {
      display: flex;
      gap: 6px;
    }
    .btn-icon-action {
      background: transparent;
      border: none;
      color: var(--vscode-descriptionForeground);
      cursor: pointer;
      font-size: 10px;
      padding: 2px 4px;
      border-radius: 3px;
      text-decoration: underline;
    }
    .btn-icon-action:hover {
      color: var(--vscode-foreground);
    }
    .btn-submit {
      background-color: var(--vscode-button-background, #007acc);
      color: var(--vscode-button-foreground, #fff);
      border: none;
      border-radius: 4px;
      padding: 4px 10px;
      font-size: 11px;
      font-weight: bold;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .btn-submit:hover {
      background-color: var(--vscode-button-hoverBackground, #0062a3);
    }
    .btn-submit svg {
      width: 10px;
      height: 10px;
      fill: currentColor;
    }
  </style>
</head>
<body>

  <!-- Top status indicators -->
  <div class="status-container">
    <div>
      <span id="serverDot" class="status-dot inactive"></span>
      <span id="serverStatusText">Server Offline</span>
    </div>
    <div id="pythonText">Python --</div>
  </div>

  <!-- Review / Approve panel -->
  <div id="approvalPanel" class="approval-container" style="display: none;">
    <div class="approval-title">Bản vá hoàn tất</div>
    <div class="approval-desc">
      Đã kiểm thử thành công tệp <span id="reviewFile" style="font-family: monospace;">...</span>. Tiết kiệm token: <span id="reviewSaving" style="font-weight:bold;">0%</span>.
    </div>
    <div class="approval-buttons">
      <button class="btn-approve" id="btnAccept">Đồng Ý (Accept)</button>
      <button class="btn-reject" id="btnReject">Từ Chối (Reject)</button>
    </div>
  </div>

  <!-- Chat / Log Thread -->
  <div class="thread-area" id="threadArea">
    <div class="log-entry log-system">Hệ thống Assembly Line đã sẵn sàng. Hãy nhập yêu cầu của bạn ở ô bên dưới.</div>
  </div>

  <!-- Bottom Input Box (Gemini Chat Style) -->
  <div class="input-container">
    <div class="target-file-indicator" id="fileIndicator">
      Đang sửa: Không có tệp Python nào đang mở
    </div>
    <textarea id="taskInput" placeholder="Ask assembly line to fix current file..."></textarea>
    <div class="input-actions">
      <div class="action-left">
        <button class="btn-icon-action" id="btnAutoDetect">Auto-Fix Toàn Bộ</button>
        <button class="btn-icon-action" id="btnToggleServer">Khởi Động Server</button>
        <button class="btn-icon-action" id="btnClearLog">Xóa Nhật Ký</button>
      </div>
      <button class="btn-submit" id="btnSubmit">
        <span>Gửi</span>
        <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
      </button>
    </div>
  </div>

  <script>
    const vscode = acquireVsCodeApi();
    
    const serverDot = document.getElementById('serverDot');
    const serverStatusText = document.getElementById('serverStatusText');
    const btnToggleServer = document.getElementById('btnToggleServer');
    const pythonText = document.getElementById('pythonText');
    const fileIndicator = document.getElementById('fileIndicator');
    const taskInput = document.getElementById('taskInput');
    const btnSubmit = document.getElementById('btnSubmit');
    const btnAutoDetect = document.getElementById('btnAutoDetect');
    const btnClearLog = document.getElementById('btnClearLog');
    const threadArea = document.getElementById('threadArea');

    const approvalPanel = document.getElementById('approvalPanel');
    const reviewFile = document.getElementById('reviewFile');
    const reviewSaving = document.getElementById('reviewSaving');
    const btnAccept = document.getElementById('btnAccept');
    const btnReject = document.getElementById('btnReject');

    let isServerRunning = false;

    // Handle messages from Extension backend
    window.addEventListener('message', event => {
      const message = event.data;
      switch (message.type) {
        case 'state':
          isServerRunning = message.serverRunning;
          serverDot.className = 'status-dot ' + (isServerRunning ? 'active' : 'inactive');
          serverStatusText.textContent = isServerRunning ? 'Server: Active' : 'Server: Offline';
          btnToggleServer.textContent = isServerRunning ? 'Tắt Server' : 'Khởi Động Server';

          pythonText.textContent = message.pythonVersion || 'Python --';
          
          if (message.activeFile) {
            fileIndicator.textContent = 'Đang sửa: ' + message.activeFile;
            fileIndicator.style.color = 'var(--vscode-textLink-foreground)';
          } else {
            fileIndicator.textContent = 'Đang sửa: (Hãy mở một tệp .py để kích hoạt)';
            fileIndicator.style.color = 'var(--vscode-descriptionForeground)';
          }
          break;

        case 'log':
          appendLogMessage(message.text);
          break;

        case 'clearLog':
          threadArea.innerHTML = '<div class="log-entry log-system">Nhật ký đã được xóa.</div>';
          break;

        case 'pendingReview':
          if (message.visible) {
            reviewFile.textContent = message.file;
            reviewSaving.textContent = message.saving + '%';
            approvalPanel.style.display = 'block';
          } else {
            approvalPanel.style.display = 'none';
          }
          break;
      }
    });

    function appendLogMessage(text) {
      if (!text.trim()) return;
      const cleanText = text.trim();
      const div = document.createElement('div');
      
      if (cleanText.startsWith('[') || cleanText.startsWith('---') || cleanText.startsWith('+++')) {
        div.className = 'log-entry log-system';
      } else {
        div.className = 'log-entry';
      }
      
      div.textContent = cleanText;
      threadArea.appendChild(div);
      threadArea.scrollTop = threadArea.scrollHeight;
    }

    // Input handlers
    btnSubmit.addEventListener('click', () => {
      const task = taskInput.value.trim();
      if (!task) return;
      vscode.postMessage({ type: 'runFix', task: task });
      taskInput.value = '';
    });

    taskInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        btnSubmit.click();
      }
    });

    btnToggleServer.addEventListener('click', () => {
      if (isServerRunning) {
        vscode.postMessage({ type: 'stopServer' });
      } else {
        vscode.postMessage({ type: 'startServer' });
      }
    });

    btnAutoDetect.addEventListener('click', () => {
      vscode.postMessage({ type: 'runAutoDetect' });
    });

    btnClearLog.addEventListener('click', () => {
      vscode.postMessage({ type: 'clearConsole' });
    });

    btnAccept.addEventListener('click', () => {
      vscode.postMessage({ type: 'acceptPatch' });
    });

    btnReject.addEventListener('click', () => {
      vscode.postMessage({ type: 'rejectPatch' });
    });

    // Refresh state
    setInterval(() => {
      vscode.postMessage({ type: 'refreshState' });
    }, 2000);
  </script>
</body>
</html>`;
  }
}

async function activate(context) {
  globalSidebarProvider = new SidebarProvider(context);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      'copilotLmBridge.sidebarView',
      globalSidebarProvider
    )
  );

  // Auto-detect when active editor switches
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(() => {
      if (globalSidebarProvider) {
        globalSidebarProvider.updateState();
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('copilotLmBridge.startServer', async () => {
      try {
        await startServer();
        vscode.window.showInformationMessage('Copilot LM Bridge server started.');
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`Failed to start Copilot LM Bridge: ${message}`);
      }
      if (globalSidebarProvider) {
        globalSidebarProvider.updateState();
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('copilotLmBridge.stopServer', async () => {
      try {
        await stopServer();
        vscode.window.showInformationMessage('Copilot LM Bridge server stopped.');
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`Failed to stop Copilot LM Bridge: ${message}`);
      }
      if (globalSidebarProvider) {
        globalSidebarProvider.updateState();
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('copilotLmBridge.requestConsent', requestConsent)
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('copilotLmBridge.runPipelineFix', async () => {
      try {
        await runPipelineFixCommand();
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`Copilot LM Bridge pipeline run failed: ${message}`);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('copilotLmBridge.autoDetectFix', async () => {
      try {
        await runAutoDetectFixCommand();
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`Copilot LM Bridge auto-detect failed: ${message}`);
      }
    })
  );

  if (getConfig().autoStart) {
    try {
      await startServer();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      vscode.window.showWarningMessage(`Copilot LM Bridge auto-start failed: ${message}`);
    }
  }
}

async function deactivate() {
  await stopServer();
}

module.exports = {
  activate,
  deactivate,
};
