const state = {
  config: null,
  source: "",
  selectedTemplateId: null,
  generated: null,
  matchResult: null,
  search: "",
  llmSettings: {
    apiKey: "",
    baseUrl: "https://coding.dashscope.aliyuncs.com/v1",
    model: "qwen3-coder-plus",
    insecureSSL: false
  }
};

const els = {
  importFile: document.getElementById("import-file"),
  saveWorkspace: document.getElementById("save-workspace"),
  resetWorkspace: document.getElementById("reset-workspace"),
  exportConfig: document.getElementById("export-config"),
  templateSearch: document.getElementById("template-search"),
  templateList: document.getElementById("template-list"),
  workspaceMeta: document.getElementById("workspace-meta"),
  addTemplate: document.getElementById("add-template"),
  duplicateTemplate: document.getElementById("duplicate-template"),
  deleteTemplate: document.getElementById("delete-template"),
  editorRoot: document.getElementById("editor-root"),
  generatorInput: document.getElementById("generator-input"),
  generatorResult: document.getElementById("generator-result"),
  generateTemplate: document.getElementById("generate-template"),
  llmApiKey: document.getElementById("llm-api-key"),
  llmBaseUrl: document.getElementById("llm-base-url"),
  llmModel: document.getElementById("llm-model"),
  llmInsecureSsl: document.getElementById("llm-insecure-ssl"),
  matchInput: document.getElementById("match-input"),
  scopeCurrentTemplate: document.getElementById("scope-current-template"),
  runMatch: document.getElementById("run-match"),
  matchResult: document.getElementById("match-result")
};

await bootstrap();

async function bootstrap() {
  hydrateLlmSettings();
  bindTopLevelEvents();
  const payload = await api("/api/workspace");
  state.config = payload.config;
  state.source = payload.source;
  state.llmSettings = {
    apiKey: localStorage.getItem("templateStudio.apiKey") || payload.llmDefaults.apiKey || "",
    baseUrl: localStorage.getItem("templateStudio.baseUrl") || payload.llmDefaults.baseUrl,
    model: localStorage.getItem("templateStudio.model") || payload.llmDefaults.model,
    insecureSSL: readBooleanSetting("templateStudio.insecureSSL", payload.llmDefaults.insecureSSL)
  };
  if (state.config.templates.length) {
    state.selectedTemplateId = state.config.templates[0].template_id;
  }
  renderAll();
}

function bindTopLevelEvents() {
  els.importFile.addEventListener("change", handleImportFile);
  els.saveWorkspace.addEventListener("click", handleSaveWorkspace);
  els.resetWorkspace.addEventListener("click", handleResetWorkspace);
  els.exportConfig.addEventListener("click", handleExportConfig);
  els.templateSearch.addEventListener("input", (event) => {
    state.search = event.target.value.trim().toLowerCase();
    renderTemplateList();
  });
  els.addTemplate.addEventListener("click", () => {
    const template = createBlankTemplate();
    state.config.templates.unshift(template);
    state.selectedTemplateId = template.template_id;
    renderAll();
  });
  els.duplicateTemplate.addEventListener("click", () => {
    const template = getCurrentTemplate();
    if (!template) {
      return;
    }
    const next = structuredClone(template);
    next.template_id = `${template.template_id}.copy`;
    state.config.templates.unshift(next);
    state.selectedTemplateId = next.template_id;
    renderAll();
  });
  els.deleteTemplate.addEventListener("click", () => {
    const template = getCurrentTemplate();
    if (!template) {
      return;
    }
    if (!window.confirm(`确定删除模板 ${template.template_id} 吗？`)) {
      return;
    }
    state.config.templates = state.config.templates.filter((item) => item.template_id !== template.template_id);
    state.selectedTemplateId = state.config.templates[0]?.template_id || null;
    renderAll();
  });
  els.generateTemplate.addEventListener("click", handleGenerateTemplate);
  els.llmApiKey.addEventListener("change", persistLlmSettings);
  els.llmBaseUrl.addEventListener("change", persistLlmSettings);
  els.llmModel.addEventListener("change", persistLlmSettings);
  els.llmInsecureSsl.addEventListener("change", persistLlmSettings);
  els.runMatch.addEventListener("click", handleRunMatch);
}

function renderAll() {
  renderWorkspaceMeta();
  renderTemplateList();
  renderGeneratorResult();
  renderEditor();
  renderMatchResult();
  els.llmApiKey.value = state.llmSettings.apiKey;
  els.llmBaseUrl.value = state.llmSettings.baseUrl;
  els.llmModel.value = state.llmSettings.model;
  els.llmInsecureSsl.checked = Boolean(state.llmSettings.insecureSSL);
}

function renderWorkspaceMeta() {
  const count = state.config?.templates?.length || 0;
  els.workspaceMeta.textContent = `来源：${state.source} · 模板数：${count}`;
}

function renderTemplateList() {
  const templates = (state.config?.templates || []).filter((template) => {
    if (!state.search) {
      return true;
    }
    return [template.template_id, template.description].some((value) =>
      String(value || "").toLowerCase().includes(state.search)
    );
  });
  els.templateList.innerHTML = templates.length
    ? templates
        .map(
          (template) => `
            <article class="template-item ${template.template_id === state.selectedTemplateId ? "active" : ""}" data-template-id="${escapeHtml(template.template_id)}">
              <h3>${escapeHtml(template.template_id)}</h3>
              <p>${escapeHtml(template.description || "暂无描述")}</p>
            </article>
          `
        )
        .join("")
    : `<div class="muted">没有匹配到模板。</div>`;

  for (const item of els.templateList.querySelectorAll(".template-item")) {
    item.addEventListener("click", () => {
      state.selectedTemplateId = item.dataset.templateId;
      renderAll();
    });
  }
}

function renderEditor() {
  const template = getCurrentTemplate();
  if (!template) {
    els.editorRoot.innerHTML = `<div class="muted">当前没有模板，请先导入模板文件或新建模板。</div>`;
    return;
  }

  els.editorRoot.innerHTML = `
    <div class="editor-grid">
      <div class="editor-form">
        <div class="field-grid">
          <label class="field">
            <span>template_id</span>
            <input id="field-template-id" type="text" value="${escapeHtml(template.template_id)}" />
          </label>
          <label class="field">
            <span>query_mode</span>
            <input id="field-query-mode" type="text" value="${escapeHtml(template.query_mode || "metric_query")}" />
          </label>
          <label class="field full-span">
            <span>description</span>
            <textarea id="field-description" rows="3">${escapeHtml(template.description || "")}</textarea>
          </label>
          <label class="field full-span">
            <span>utterances（每行一条）</span>
            <textarea id="field-utterances" rows="6">${escapeHtml((template.utterances || []).join("\n"))}</textarea>
          </label>
          <label class="field">
            <span>required_slots（逗号分隔）</span>
            <input id="field-required-slots" type="text" value="${escapeHtml((template.required_slots || []).join(", "))}" />
          </label>
          <label class="field">
            <span>optional_slots（逗号分隔）</span>
            <input id="field-optional-slots" type="text" value="${escapeHtml((template.optional_slots || []).join(", "))}" />
          </label>
          <label class="field full-span">
            <span>must_terms（每行一组，同组内用 | 分隔）</span>
            <textarea id="field-must-terms" rows="5">${escapeHtml(formatMustTerms(template.must_terms))}</textarea>
          </label>
          <label class="field full-span">
            <span>negative_terms（逗号分隔）</span>
            <input id="field-negative-terms" type="text" value="${escapeHtml((template.negative_terms || []).join(", "))}" />
          </label>
          <label class="field full-span">
            <span>slot_constraints（JSON）</span>
            <textarea id="field-slot-constraints" class="json-editor" rows="8">${escapeHtml(formatJson(template.slot_constraints))}</textarea>
          </label>
          <label class="field full-span">
            <span>slot_extractors（JSON）</span>
            <textarea id="field-slot-extractors" class="json-editor" rows="16">${escapeHtml(formatJson(template.slot_extractors))}</textarea>
          </label>
          <label class="field full-span">
            <span>llm_slot_extraction（JSON）</span>
            <textarea id="field-llm-slot-extraction" class="json-editor" rows="8">${escapeHtml(formatJson(template.llm_slot_extraction))}</textarea>
          </label>
          <label class="field full-span">
            <span>metadata（JSON）</span>
            <textarea id="field-metadata" class="json-editor" rows="6">${escapeHtml(formatJson(template.metadata))}</textarea>
          </label>
        </div>
      </div>
      <div class="editor-side">
        <div class="badge">当前模板预览</div>
        <pre class="raw-preview" id="current-template-preview">${escapeHtml(formatJson(template))}</pre>
        <h3>编辑提示</h3>
        <ul class="hint-list">
          <li><code>query_mode</code> 当前通常固定写 <code>metric_query</code>。</li>
          <li><code>query_operator</code> 才是真正区分 <code>count / topn / list</code> 的槽位。</li>
          <li>复杂结构优先用上面的 LLM 生成，再在这里细调。</li>
          <li>JSON 文本框失焦后会自动解析并写回当前模板。</li>
        </ul>
      </div>
    </div>
  `;

  bindEditorField("field-template-id", (value) => {
    const oldId = template.template_id;
    template.template_id = value || `template.generated.${Date.now()}`;
    if (state.selectedTemplateId === oldId) {
      state.selectedTemplateId = template.template_id;
    }
    renderTemplateList();
    updateTemplatePreview();
  });
  bindEditorField("field-query-mode", (value) => {
    template.query_mode = value || "metric_query";
    updateTemplatePreview();
  });
  bindEditorField("field-description", (value) => {
    template.description = value;
    renderTemplateList();
    updateTemplatePreview();
  });
  bindEditorField("field-utterances", (value) => {
    template.utterances = splitLines(value);
    updateTemplatePreview();
  });
  bindEditorField("field-required-slots", (value) => {
    template.required_slots = splitCommaList(value);
    updateTemplatePreview();
  });
  bindEditorField("field-optional-slots", (value) => {
    template.optional_slots = splitCommaList(value);
    updateTemplatePreview();
  });
  bindEditorField("field-must-terms", (value) => {
    template.must_terms = parseMustTerms(value);
    updateTemplatePreview();
  });
  bindEditorField("field-negative-terms", (value) => {
    template.negative_terms = splitCommaList(value);
    updateTemplatePreview();
  });
  bindJsonField("field-slot-constraints", (json) => {
    template.slot_constraints = json;
  });
  bindJsonField("field-slot-extractors", (json) => {
    template.slot_extractors = json;
  });
  bindJsonField("field-llm-slot-extraction", (json) => {
    template.llm_slot_extraction = json;
  });
  bindJsonField("field-metadata", (json) => {
    template.metadata = json;
  });
}

function renderGeneratorResult() {
  if (!state.generated) {
    els.generatorResult.className = "generator-result empty";
    els.generatorResult.textContent = "尚未生成模板建议。";
    return;
  }
  const notes = Array.isArray(state.generated.analysis.notes) ? state.generated.analysis.notes : [];
  const rationale = Array.isArray(state.generated.analysis.design_rationale)
    ? state.generated.analysis.design_rationale
    : [];
  els.generatorResult.className = "generator-result";
  els.generatorResult.innerHTML = `
    <div class="pill-row">
      <span class="pill">entity: ${escapeHtml(state.generated.analysis.entity || "-")}</span>
      <span class="pill">metric: ${escapeHtml(state.generated.analysis.metric || "-")}</span>
      <span class="pill">query_operator: ${escapeHtml(state.generated.analysis.query_operator || "-")}</span>
    </div>
    <p class="muted">${escapeHtml(state.generated.analysis.intent || "模型已返回模板建议。")}</p>
    ${state.generated.analysis.template_strategy ? `<p class="muted">设计策略：${escapeHtml(state.generated.analysis.template_strategy)}</p>` : ""}
    ${notes.length ? `<ul class="hint-list">${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>` : ""}
    ${rationale.length ? `<h3>为什么这样设计</h3><ul class="hint-list">${rationale.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
    <div class="inline-actions">
      <button id="apply-generated-current">覆盖当前模板</button>
      <button id="apply-generated-new" class="secondary">新增为新模板</button>
    </div>
    <pre class="raw-preview">${escapeHtml(formatJson(state.generated.template))}</pre>
  `;

  document.getElementById("apply-generated-current")?.addEventListener("click", () => {
    const current = getCurrentTemplate();
    if (!current) {
      return;
    }
    Object.assign(current, structuredClone(state.generated.template));
    state.selectedTemplateId = current.template_id;
    renderAll();
  });
  document.getElementById("apply-generated-new")?.addEventListener("click", () => {
    const template = structuredClone(state.generated.template);
    const existingIds = new Set(state.config.templates.map((item) => item.template_id));
    let nextId = template.template_id;
    let counter = 1;
    while (existingIds.has(nextId)) {
      nextId = `${template.template_id}.${counter}`;
      counter += 1;
    }
    template.template_id = nextId;
    state.config.templates.unshift(template);
    state.selectedTemplateId = template.template_id;
    renderAll();
  });
}

function renderMatchResult() {
  if (!state.matchResult) {
    els.matchResult.className = "result-panel empty";
    els.matchResult.textContent = "尚未执行匹配测试。";
    return;
  }
  const result = state.matchResult;
  const topCandidates = result.trace?.top_candidates || [];
  els.matchResult.className = "result-panel";
  els.matchResult.innerHTML = `
    <div class="pill-row">
      <span class="pill">template_id: ${escapeHtml(String(result.template_id))}</span>
      <span class="pill">status: ${escapeHtml(result.status)}</span>
      <span class="pill">score: ${escapeHtml(Number(result.score || 0).toFixed(4))}</span>
      <span class="pill">query_mode: ${escapeHtml(result.query_mode || "-")}</span>
    </div>
    <h3>抽取槽位</h3>
    <pre class="raw-preview">${escapeHtml(formatJson(result.slots || {}))}</pre>
    <h3>Top Candidates</h3>
    <pre class="raw-preview">${escapeHtml(formatJson(topCandidates))}</pre>
  `;
}

function updateTemplatePreview() {
  const template = getCurrentTemplate();
  const preview = document.getElementById("current-template-preview");
  if (template && preview) {
    preview.textContent = formatJson(template);
  }
}

function bindEditorField(id, onCommit) {
  const element = document.getElementById(id);
  if (!element) {
    return;
  }
  element.addEventListener("change", (event) => onCommit(event.target.value));
}

function bindJsonField(id, onCommit) {
  const element = document.getElementById(id);
  if (!element) {
    return;
  }
  element.addEventListener("change", (event) => {
    try {
      const parsed = JSON.parse(event.target.value || "{}");
      onCommit(parsed);
      updateTemplatePreview();
    } catch (error) {
      window.alert(`JSON 解析失败：${error.message}`);
      event.target.focus();
    }
  });
}

async function handleImportFile(event) {
  const file = event.target.files?.[0];
  if (!file) {
    return;
  }
  const text = await file.text();
  try {
    const config = JSON.parse(text);
    const payload = await api("/api/workspace/save", {
      method: "POST",
      body: JSON.stringify({ config })
    });
    state.config = payload.config;
    state.source = "workspace";
    state.selectedTemplateId = state.config.templates[0]?.template_id || null;
    state.generated = null;
    state.matchResult = null;
    renderAll();
  } catch (error) {
    window.alert(`导入失败：${error.message}`);
  } finally {
    event.target.value = "";
  }
}

async function handleSaveWorkspace() {
  const payload = await api("/api/workspace/save", {
    method: "POST",
    body: JSON.stringify({ config: state.config })
  });
  state.config = payload.config;
  state.source = "workspace";
  renderWorkspaceMeta();
  window.alert(`工作区已保存到 ${payload.workspacePath}`);
}

async function handleResetWorkspace() {
  if (!window.confirm("确定要恢复默认模板吗？当前未保存修改会丢失。")) {
    return;
  }
  const payload = await api("/api/workspace/reset", { method: "POST" });
  state.config = payload.config;
  state.source = payload.source;
  state.selectedTemplateId = state.config.templates[0]?.template_id || null;
  state.generated = null;
  state.matchResult = null;
  renderAll();
}

function handleExportConfig() {
  const blob = new Blob([`${formatJson(state.config)}\n`], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "templates.studio.export.json";
  anchor.click();
  URL.revokeObjectURL(url);
}

async function handleGenerateTemplate() {
  const text = els.generatorInput.value.trim();
  if (!text) {
    window.alert("请先输入一句要抽象成模板的话。");
    return;
  }
  syncLlmSettingsFromInputs();
  els.generateTemplate.disabled = true;
  els.generateTemplate.textContent = "生成中...";
  try {
    const payload = await api("/api/llm/generate-template", {
      method: "POST",
      body: JSON.stringify({
        text,
        config: state.config,
        settings: state.llmSettings
      })
    });
    state.generated = payload;
    renderGeneratorResult();
  } catch (error) {
    window.alert(`模板生成失败：${error.message}`);
  } finally {
    els.generateTemplate.disabled = false;
    els.generateTemplate.textContent = "生成模板建议";
  }
}

async function handleRunMatch() {
  const text = els.matchInput.value.trim();
  if (!text) {
    window.alert("请先输入要测试的 query。");
    return;
  }
  els.runMatch.disabled = true;
  els.runMatch.textContent = "测试中...";
  try {
    const templateIds = els.scopeCurrentTemplate.checked && state.selectedTemplateId ? [state.selectedTemplateId] : null;
    const payload = await api("/api/match", {
      method: "POST",
      body: JSON.stringify({
        text,
        config: state.config,
        templateIds
      })
    });
    state.matchResult = payload.result;
    renderMatchResult();
  } catch (error) {
    window.alert(`匹配测试失败：${error.message}`);
  } finally {
    els.runMatch.disabled = false;
    els.runMatch.textContent = "运行匹配测试";
  }
}

function getCurrentTemplate() {
  return state.config?.templates?.find((template) => template.template_id === state.selectedTemplateId) || null;
}

function createBlankTemplate() {
  return {
    template_id: `template.generated.${Date.now()}`,
    query_mode: "metric_query",
    description: "",
    utterances: [],
    required_slots: ["query_operator"],
    optional_slots: [],
    must_terms: [],
    negative_terms: ["原因", "根因", "报告", "总结", "预测"],
    slot_constraints: {},
    slot_extractors: {},
    llm_slot_extraction: {
      enabled: false,
      slots: [],
      instructions: ""
    },
    metadata: {}
  };
}

function splitLines(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function splitCommaList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseMustTerms(value) {
  return splitLines(value).map((line) =>
    line
      .split("|")
      .map((item) => item.trim())
      .filter(Boolean)
  );
}

function formatMustTerms(value) {
  return (value || []).map((group) => group.join(" | ")).join("\n");
}

function formatJson(value) {
  return JSON.stringify(value || {}, null, 2);
}

function hydrateLlmSettings() {
  state.llmSettings = {
    apiKey: localStorage.getItem("templateStudio.apiKey") || "",
    baseUrl: localStorage.getItem("templateStudio.baseUrl") || state.llmSettings.baseUrl,
    model: localStorage.getItem("templateStudio.model") || state.llmSettings.model,
    insecureSSL: readBooleanSetting("templateStudio.insecureSSL", state.llmSettings.insecureSSL)
  };
}

function syncLlmSettingsFromInputs() {
  state.llmSettings = {
    apiKey: els.llmApiKey.value.trim(),
    baseUrl: els.llmBaseUrl.value.trim(),
    model: els.llmModel.value.trim(),
    insecureSSL: Boolean(els.llmInsecureSsl.checked)
  };
  persistLlmSettings();
}

function persistLlmSettings() {
  state.llmSettings = {
    apiKey: els.llmApiKey.value.trim(),
    baseUrl: els.llmBaseUrl.value.trim(),
    model: els.llmModel.value.trim(),
    insecureSSL: Boolean(els.llmInsecureSsl.checked)
  };
  localStorage.setItem("templateStudio.apiKey", state.llmSettings.apiKey);
  localStorage.setItem("templateStudio.baseUrl", state.llmSettings.baseUrl);
  localStorage.setItem("templateStudio.model", state.llmSettings.model);
  localStorage.setItem("templateStudio.insecureSSL", state.llmSettings.insecureSSL ? "1" : "0");
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json"
    },
    ...options
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function readBooleanSetting(key, fallback = false) {
  const raw = localStorage.getItem(key);
  if (raw == null) {
    return Boolean(fallback);
  }
  return raw === "1" || raw === "true";
}
