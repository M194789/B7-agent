const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const e = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  table:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M9 9v11M3 14h18"/>',
  list:'<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  settings:'<path d="m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h6l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',
  arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
  upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  alert:'<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3v.1"/>',
  file:'<path d="M14 2H5a1 1 0 0 0-1 1v18a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V8Zm0 0v6h6M8 13h8M8 17h5"/>',
  spark:'<path d="m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5L12 2Z"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  download:'<path d="M12 3v13m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  gauge:'<path d="M4 18a8 8 0 1 1 16 0"/><path d="m12 18 4-6"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.file}</svg>`;
const state = {config:null,tasks:[],task:null,page:'new',tab:'result',filter:'all',search:'',files:[],modFiles:[],provider:'deepseek',busy:false,evaluation:null};
const labels = {new:'新建任务',tasks:'全部任务',evaluation:'效果评测',settings:'模型设置',task:'任务'};
const kindNames = {grades:'课程成绩总评',appraisal:'工作考核评分'};
const statuses = {queued:['等待执行','blue'],running:['处理中','blue'],waiting_review:['等你确认','amber'],completed:['已完成','green'],failed:['需要处理','red'],cancelled:['已切换',''],stopped:['已中止','']};
const modeNames = {rule:'规则处理',model:'实际模型调用',human:'人工确认'};
const badge = (label,color='') => `<span class="badge ${color}">${e(label)}</span>`;
const statusBadge = code => badge(...(statuses[code] || [code,'']));
const date = value => value ? new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '—';

async function api(path, options={}) {
  const response = await fetch(path, options);
  let body;
  try { body = await response.json(); } catch { throw new Error(`请求未完成（HTTP ${response.status}）`); }
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '请检查输入内容后重试。');
  return body;
}
const post = (path, body={}) => api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
let toastTimer;
function toast(message) { const el=$('#toast');el.textContent=message;el.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.hidden=true,5500); }
function navigate(page) { location.hash=page; }

function renderNav() {
  const pending = state.tasks.filter(t=>t.status==='waiting_review').length;
  $('#nav').innerHTML = [['new','plus'],['tasks','list'],['evaluation','gauge'],['settings','settings']].map(([page,glyph])=>`<a class="nav-item ${state.page===page || state.page==='task'&&page==='tasks'?'active':''}" href="#${page}" aria-label="${labels[page]}" ${state.page===page?'aria-current="page"':''}>${icon(glyph)}<span>${labels[page]}</span>${page==='tasks'&&pending?`<span class="nav-count">${pending}</span>`:''}</a>`).join('');
  $('#breadcrumb-current').textContent = labels[state.page] || '工作台';
  $('#connection-label').textContent = state.config?.model.configured ? `已连接 ${state.config.model.model}` : '模型未连接';
}

function stat(label,value,sub,glyph='list',tone='') {
  return `<div class="stat"><div class="stat-top"><span>${label}</span>${icon(glyph)}</div><div class="stat-value ${tone}">${value}</div><div class="stat-bottom">${sub}</div></div>`;
}
function empty(title='还没有任务', subtitle='从上方选择一个流程，或用内置样例开始体验。') {
  return `<div class="empty">${icon('list')}<strong>${title}</strong><small>${subtitle}</small></div>`;
}
function taskTable(tasks) {
  if(!tasks.length) return empty();
  return `<div class="table-wrap"><table class="task-table"><thead><tr><th>任务名称</th><th>类型</th><th>状态</th><th>执行方式</th><th>创建时间</th><th></th></tr></thead><tbody>${tasks.map(t=>`<tr data-task="${e(t.id)}" tabindex="0" role="link" aria-label="打开任务 ${e(t.name)}"><td><div class="task-title">${icon('table')}${e(t.name)}</div><div class="cell-sub">${e(t.step)}</div></td><td>${kindNames[t.kind]||t.kind}</td><td>${statusBadge(t.status)}</td><td><span class="muted">${t.llm_used?'模型辅助':'规则流程'}</span></td><td class="mono muted">${date(t.created_at)}</td><td class="muted">↗</td></tr>`).join('')}</tbody></table></div>`;
}

// ---------------------------------------------------------------- the single entrance
function newPage() {
  const configured=state.config.model.configured,limits=state.config.limits;
  return `<div class="page-heading"><div><div class="eyebrow">NEW TASK</div><h1>把材料交给我，把规则告诉我。</h1><p>成绩表、平台导出、照片、PDF、证明材料都可以一起上传。系统自动整合、去重，按你的规则算分，只在需要时请你确认。</p></div></div>
  ${configured?'':'<div class="notice amber">还没有连接模型：照片、PDF 识别和理解评分规则都需要模型。请先到 <a class="settings-link" href="#settings">模型设置</a> 连接。</div>'}
  <div class="form-layout"><section class="card"><div class="card-body"><form id="task-form">
  ${flowFields()}
  <div class="form-field"><label class="form-label">材料 <small>最多 ${limits.files} 个，单个不超过 ${limits.upload_mb}MB</small></label><label class="dropzone" id="dropzone" for="file-input">${icon('upload')}<b>把所有材料拖到这里，或点击选择</b><small>学习通 / 雨课堂 / 教务导出的表格、手写登分表照片、PDF 成绩单、证书、工作记录、名单……混在一起也可以；整个文件夹或 zip 压缩包也能直接拖进来</small><input id="file-input" type="file" multiple accept=".csv,.tsv,.xlsx,.xls,.docx,.pdf,.txt,.md,.jpg,.jpeg,.png,.webp,.zip" hidden></label><div class="button-row" style="margin-top:8px"><button class="button small" type="button" data-action="pick-folder">${icon('upload')}选择文件夹</button><input id="folder-input" type="file" webkitdirectory multiple hidden></div><div class="file-list" id="file-list"></div></div>
  <div class="form-field"><label class="form-label" for="rules-text">评分规则 <small>用自己的话写、粘贴，或从文件读取（TXT / Word / PDF）</small><button class="button ghost small" type="button" data-action="pick-rules" style="margin-left:8px">从文件读取</button><input id="rules-file" type="file" accept=".txt,.md,.docx,.pdf" hidden></label><textarea id="rules-text" name="rules_text" rows="6" placeholder="例如：小测占20%，三次去掉最低一次取平均；作业10%；期中20%，期末50%；缺考按0分，缓考待定，总评取整。&#10;&#10;也可以粘贴整份考核方案，如“学生竞赛获奖每个项目计2分，最高10分；须提交工作日志、谈话记录，缺一项扣5分……”"></textarea><div class="form-help">只想整合、去重而不算分，可以不填。规则文件也可以和材料一起拖进来，系统会认出它。规则会先给你确认，再由程序精确计算。</div></div>
  <details class="form-field"><summary class="form-label" style="cursor:pointer">更多选项 <small>都可以不填</small></summary><div class="two-col" style="margin-top:10px"><div class="form-field"><label class="form-label" for="task-name">任务名称</label><input id="task-name" name="name" type="text" maxlength="100" placeholder="如：数据结构 2026秋 总评"></div><div class="form-field"><label class="form-label" for="course">课程名称</label><input id="course" name="course" type="text" maxlength="100" placeholder="表格里没有课程名时使用"></div></div><div class="form-field"><label class="form-label" for="people">被考核人名单 <small>工作考核用，不填则从材料中识别</small></label><textarea id="people" name="people" rows="2" placeholder="王敏、李强、赵琳"></textarea></div></details>
  <div class="form-actions"><small class="muted">原始材料只保存在本机；模型会收到识别所需的内容，演示请用合成或脱敏材料。</small><button class="button primary" type="submit" id="create-submit">开始处理 ${icon('arrow')}</button></div></form></div></section>
  <aside class="form-aside">${prefsCard()}<section class="card side-card"><h3>接下来会发生什么</h3><ol class="numbered-list"><li>自动识别每份材料：表格、照片、PDF、证书都会读出来</li><li>整合到人：去掉重复，找出冲突、缺考、名单外的人</li><li>按你的规则算分，把结果和需要你决定的问题放在一页请你确认</li></ol></section>
  <section class="card side-card"><h3>先用样例试试</h3><p>都是合成数据，每份都埋了常见问题。</p><div style="display:grid;gap:8px;margin-top:12px"><button class="button small" data-demo="course">${icon('spark')}课程总评：学习通 + 教务 + 手写照片</button><button class="button small" data-demo="appraisal">${icon('spark')}辅导员考核：30 份证明材料</button><button class="button small" data-demo="grades">${icon('spark')}只整合三平台成绩，不算分</button></div></section></aside></div>
  <div style="margin-top:26px"><div class="section-heading"><h2>最近任务</h2><a class="button ghost" href="#tasks">全部任务 →</a></div><section class="card">${taskTable(state.tasks.slice(0,5))}</section></div>`;
}

// The flow for this task (preset from the usual one, changeable every time) and an optional confirmed rule template.
function flowFields() {
  const prefs=state.config.prefs||{},templates=state.config.templates||[];
  return `<div class="two-col"><div class="form-field"><label class="form-label" for="task-kind">流程 <small>${prefs.flow?'已按你的常用流程预选，可以改':'不选则由系统判断'}</small></label><select id="task-kind" name="kind"><option value="">自动判断</option>${Object.entries(state.config.kinds).map(([k,l])=>`<option value="${k}" ${prefs.flow===k?'selected':''}>${e(l)}</option>`).join('')}</select><input type="hidden" name="kind_source" id="kind-source" value="${prefs.flow?'pref':''}"></div>
  <div class="form-field"><label class="form-label" for="task-template">规则模板 <small>${templates.length?'用以前确认过的规则':'还没有模板：任务完成后可以保存'}</small></label><select id="task-template" name="template" ${templates.length?'':'disabled'}><option value="">不用模板</option>${templates.map(t=>`<option value="${e(t.id)}">${e(t.name)} · ${e(state.config.kinds[t.kind]||t.kind)}</option>`).join('')}</select></div></div>`;
}
function prefsCard() {
  const prefs=state.config.prefs||{};
  return `<section class="card side-card"><h3>我的常用设置</h3><p class="muted" style="font-size:13px">设了常用流程，新建任务时直接选好，不用系统再判断；每次仍可以改。</p><div style="display:grid;gap:8px;margin-top:10px"><select id="pref-identity" aria-label="身份"><option value="">身份（可不填）</option>${(state.config.identities||[]).map(x=>`<option ${prefs.identity===x?'selected':''}>${e(x)}</option>`).join('')}</select><select id="pref-flow" aria-label="常用流程"><option value="">常用流程：每次自动判断</option>${Object.entries(state.config.kinds).map(([k,l])=>`<option value="${k}" ${prefs.flow===k?'selected':''}>常用流程：${e(l)}</option>`).join('')}</select><button class="button small" type="button" data-action="save-prefs">保存</button></div>
  ${(state.config.templates||[]).length?`<h3 style="margin-top:16px">规则模板</h3><ul class="rule-list" style="list-style:none;padding:0">${state.config.templates.map(t=>`<li style="display:flex;gap:6px;align-items:baseline"><span style="flex:1">${e(t.name)} <small class="muted">${e(state.config.kinds[t.kind]||'')}</small></span><button class="button ghost small" type="button" data-delete-template="${e(t.id)}">删除</button></li>`).join('')}</ul>`:''}</section>`;
}

function tasksPage() {
  let tasks=state.tasks.filter(t=>(state.filter==='all'||t.status===state.filter)&&(!state.search||t.name.toLowerCase().includes(state.search.toLowerCase())));
  return `<div class="page-heading"><div><div class="eyebrow">TASK HISTORY</div><h1>全部任务</h1><p>任务状态自动保存，可以随时回来继续确认。</p></div><a class="button primary" href="#new">${icon('plus')}新建任务</a></div><section class="card"><div class="card-head"><div class="filters">${[['all','全部'],['waiting_review','等你确认'],['running','处理中'],['completed','已完成'],['failed','需处理']].map(([key,label])=>`<button class="filter ${state.filter===key?'active':''}" data-filter="${key}">${label}${key==='all'?` · ${state.tasks.length}`:''}</button>`).join('')}</div><input class="search-input" id="task-search" aria-label="搜索任务" placeholder="搜索任务名称…" value="${e(state.search)}"></div><div id="task-table-result">${taskTable(tasks)}</div></section>`;
}

// ---------------------------------------------------------------- task page
function taskPage() {
  const t=state.task;
  if(!t) return '<div class="loading">正在载入任务…</div>';
  const det=t.result?.pending?.detected||t.result?.detected||t.request?.detected;
  const switchable=['waiting_review','failed'].includes(t.status);
  const head=`<a class="back-link" href="#tasks">← 全部任务</a><div class="page-heading"><div><div class="eyebrow">${t.kind==='appraisal'?'WORK APPRAISAL':'COURSE GRADES'} <span class="task-key">/ ${e(t.id.slice(0,8).toUpperCase())}</span></div><h1 style="font-size:24px">${e(t.name)}${t.version>1?` <small class="muted" style="font-size:14px">第 ${t.version} 版</small>`:''}</h1><p>${date(t.created_at)} 创建${det?` · 已识别为<b>${e(det.label)}</b>${det.reason?`（${e(det.reason)}）`:''}`:''}${switchable?` <button class="button ghost small" data-action="switch">不对，改为${t.kind==='grades'?'工作考核评分':'课程成绩总评'}</button>`:''}</p></div>${statusBadge(t.status)}</div>`;
  const top=head+stateBanner(t);
  if(['queued','running'].includes(t.status)) return top+progressView(t);
  if(t.status==='failed') return top+`<div class="notice red">${e(t.error)}<div style="margin-top:10px"><button class="button small" data-action="retry">重试</button></div></div>${changePanel(t)}${progressView(t)}`;
  if(t.status==='stopped') return top+`<div class="notice">${e(t.step)}。<div style="margin-top:10px"><button class="button small primary" data-action="retry">继续处理</button></div></div>${changePanel(t)}`;
  if(t.status==='cancelled') return head+`<div class="notice">${e(t.step)}。这个任务的材料已用另一种方式重新处理，可在全部任务中找到新的任务。</div>`;
  if(t.status==='waiting_review') {
    const p=t.result.pending;
    if(p.stage==='mapping') return top+changePanel(t)+mappingQuestion(t,p);
    if(p.stage==='understand') return top+changePanel(t)+understandQuestion(t,p);
    return top+changesNotice(p.changes)+changePanel(t)+(t.kind==='appraisal'?appraisalConfirm(t,p):gradesConfirm(t,p));
  }
  return top+changesNotice(t.result.changes)+changePanel(t)+resultPage(t);
}

// Which of the three the result is: the system is processing, things wait for the user, or the user confirmed.
function stateBanner(t) {
  const s=t.state||{},code=s.code;
  if(!code||code==='cancelled')return '';
  const step=code==='processing'?0:['needs_review','system_done'].includes(code)?1:['confirmed','confirmed_partial'].includes(code)?2:-1;
  const steps=['系统处理','待你确认','你已确认'];
  const tone={needs_review:'amber',system_done:'blue',confirmed:'green',confirmed_partial:'amber',stopped:'',failed:'red'}[code]||'';
  return `<div class="notice ${tone}" style="display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center"><span style="display:flex;gap:6px;flex-wrap:wrap">${steps.map((x,i)=>`<span class="badge ${i===step?(tone||'blue'):i<step?'green':''}">${i<step?'✓ ':''}${x}</span>`).join('<span class="muted">→</span>')}</span><b>${e(s.text)}</b>${code==='needs_review'||code==='system_done'?'<small class="muted">确认之前的结果都是暂定的</small>':''}</div>`;
}

// What a new version changed against the one before: kept, lapsed and revoked decisions, whose totals moved.
function changesNotice(c) {
  if(!c)return '';
  const files=[['files_added','新增'],['files_replaced','替换'],['files_removed','删除']].filter(([k])=>c[k]?.length).map(([k,l])=>`${l} ${c[k].map(e).join('、')}`);
  const value=(x)=>x==null?'—':x[0]!=null?x[0]:({pending:'待定',invalid:'无效',exempt:'免修'}[x[1]]||'待定');
  const moved=c.totals_moved||[];
  const lines=[
    files.length?`材料：${files.join('；')}`:'',
    (c.files_same||[]).length?`${c.files_same.map(x=>`“${e(x.name)}”与“${e(x.same_as)}”内容相同，没有重复加入`).join('；')}`:'',
    c.rules_changed?'规则原文改了，已按新规则重新理解（之前对规则的修改需要重新核对）。':'规则沿用上一版'+(c.previous?'（包括你在确认页做的修改）':'')+'。',
    c.kept!=null?`沿用之前的处理 ${c.kept} 项。`:'',
    (c.lapsed||[]).length?`<b style="color:var(--amber)">${c.lapsed.length} 项之前的处理已失效，需要重新决定</b>（对应的记录变了）：${c.lapsed.map(x=>`${e(x.title||'')}（原来：${e(x.label)}）`).join('；')}`:'',
    (c.revoked||[]).length?`撤回了 ${c.revoked.length} 项处理：${c.revoked.map(x=>`${e(x.title)}（原来：${e(x.label)}）`).join('；')}`:'',
    (c.moot||[]).length?`${c.moot.length} 项之前的处理不再需要（相关的记录已不存在）：${c.moot.map(x=>e(x.title)).join('；')}`:'',
    (c.dropped_fills||[]).length?`补录的值已有原始记录，不再使用：${c.dropped_fills.map(e).join('；')}`:'',
    c.overrides?`结果中手动修改的 ${c.overrides} 处仍然保留。`:'',
    c.records&&c.records[0]!=null?`整合记录：${c.records[0]} 条 → ${c.records[1]} 条。`:'',
    moved.length?`<b>${moved.length} 人的总评有变化</b>${c.totals_same!=null?`，其余 ${c.totals_same} 人不变`:''}：${moved.slice(0,30).map(x=>`${e(x.student_id)} ${e(x.student_name)} ${value(x.before)} → ${value(x.after)}`).join('；')}${moved.length>30?' 等':''}`:(c.totals_same!=null&&c.previous?`所有人的总评都没有变化。`:''),
  ].filter(Boolean);
  return `<details class="card" open><summary class="card-head" style="cursor:pointer"><h2>这一版改了什么</h2><small class="muted">与第 ${c.previous||'—'} 版相比</small></summary><div class="card-body">${c.was_confirmed?`<div class="notice amber" style="margin-bottom:10px">第 ${c.previous} 版已确认的结果已失效。确认这一版后，才是新的正式结果；需要旧结果可以“撤回到上一版”。</div>`:''}<ul class="rule-list">${lines.map(x=>`<li>${x}</li>`).join('')}</ul></div></details>`;
}

// Add, replace or remove materials, change the rules, take back the last change. Available whenever nothing is running.
function changePanel(t) {
  const rules=t.rules_now??'';
  return `<details class="card" id="change-panel"><summary class="card-head" style="cursor:pointer"><h2>修改材料或规则</h2><small class="muted">补交、删错、改规则都可以；没变的材料不会重新识别，之前的处理会尽量沿用</small></summary><div class="card-body">
  <div class="form-help" style="margin-bottom:8px">现有材料（勾选要删除的）：</div><div style="display:flex;flex-direction:column;gap:4px;margin-bottom:12px">${t.files.map(f=>`<label class="check"><input type="checkbox" data-remove-index="${f.index}"> ${e(f.name)}${f.role?' <small class="muted">名单</small>':''}</label>`).join('')}</div>
  <div class="form-actions" style="justify-content:flex-start;gap:8px;margin-bottom:6px"><label class="button small">${icon('file')}添加文件<input type="file" id="mod-file-input" multiple hidden></label><label class="button small">添加文件夹<input type="file" id="mod-folder-input" webkitdirectory multiple hidden></label><small class="muted">同名文件会替换原来的那份</small></div><div id="mod-file-list" style="margin-bottom:12px"></div>
  <label class="rule-field"><span>${t.kind==='appraisal'?'考核方案':'评分规则'}（改了才会重新理解）</span><textarea id="mod-rules" rows="${Math.min(10,Math.max(3,rules.split('\n').length+1))}" maxlength="6000">${e(rules)}</textarea></label>
  <div class="form-actions" style="margin-top:12px;justify-content:flex-start;gap:8px"><button class="button primary small" type="button" data-action="modify">按修改重新处理 ${icon('arrow')}</button>${t.status==='completed'?'<button class="button small" type="button" data-action="reopen">回到确认页修改处理</button>':''}${t.version>1?`<button class="button ghost small" type="button" data-action="undo">撤回到第 ${t.version-1} 版</button>`:''}</div>
  ${t.status==='completed'?'<div class="form-help" style="margin-top:8px">修改后，当前已确认的结果会标为失效，新结果需要你再确认一次。</div>':''}</div></details>`;
}

function progressView(t) {
  const events=(t.events||[]).filter(x=>x.mode!=='human').slice(-8);
  return `<section class="card"><div class="card-body"><div class="progress-panel" style="margin:0 0 14px"><span class="spinner"></span><span>${e(t.step)}……识别照片和阅读材料可能需要一两分钟，页面会自动更新。</span>${t.status==='running'&&!/正在中止/.test(t.step)?'<button class="button ghost small" data-action="stop" style="margin-left:auto">中止</button>':''}</div><ul class="rule-list">${events.map(x=>`<li>${x.status==='running'?'<span class="spinner"></span> ':x.status==='failed'?'✕ ':'✓ '}${e(x.title)}${x.elapsed_ms!=null&&x.status!=='running'?` <small class="muted">${(x.elapsed_ms/1000).toFixed(1)} 秒</small>`:''}</li>`).join('')}</ul></div></section>`;
}

// Only asked when the system cannot tell where the student or the score is.
function mappingQuestion(t,p) {
  const sel=(table,key,label)=>`<label class="rule-field"><span>${label}</span><select data-map-table="${e(table.id)}" data-map-field="${key}"><option value="">没有这一列</option>${table.headers.map(h=>`<option value="${e(h)}" ${table.mapping[key]===h?'selected':''}>${e(h)}</option>`).join('')}</select></label>`;
  return `<form id="confirm-form" data-kind="mapping"><div class="notice amber">有 ${p.tables.length} 张表系统看不出哪一列是学生、哪一列是成绩，请指一下。其余的表已经自动处理好了。</div>${p.tables.map(table=>`<section class="review-card"><div class="review-head"><span class="review-number">${icon('table')}</span><div><strong>${e(table.name)}</strong><small>${e(table.text||'')}</small></div></div><div class="table-wrap" style="margin:10px 0"><table><thead><tr>${table.headers.map(h=>`<th>${e(h)}</th>`).join('')}</tr></thead><tbody>${table.preview.slice(0,5).map(row=>`<tr>${table.headers.map(h=>`<td>${e(row[h])}</td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="rule-card">${sel(table,'student_id','学号在哪一列')}${sel(table,'student_name','姓名在哪一列')}${sel(table,'score','成绩在哪一列')}</div><div class="form-help" style="margin-top:8px">如果每次测验、作业各占一列，勾选这些列：<span class="filters" style="display:inline-flex">${table.headers.map(h=>`<label class="check"><input type="checkbox" data-item-table="${e(table.id)}" value="${e(h)}" ${(table.mapping.item_columns||[]).includes(h)?'checked':''}>${e(h)}</label>`).join('')}</span></div></section>`).join('')}
  <div class="review-submit"><small>指明后会继续自动处理。</small><button class="button primary" type="submit">继续 ${icon('arrow')}</button></div></form>`;
}

// Before any photo is read: how the task is understood, and the few things the rules leave open.
function planBody(plan) {
  const answered=(plan.questions||[]).map((q,i)=>[q,(plan.answers||[])[i]]).filter(([,a])=>a);
  return `<ul class="rule-list">${plan.subject?`<li>考核对象：${e(plan.subject)}</li>`:''}${plan.scope?`<li>范围：${e(plan.scope)}</li>`:''}<li>完整性：${e(plan.baseline_note||'')}</li>${(plan.understood||[]).map(x=>`<li>${e(x)}</li>`).join('')}${answered.map(([q,a])=>`<li>你补充的：${e(q.question)} → <b>${e(a)}</b></li>`).join('')}${plan.note?`<li>你补充的：${e(plan.note)}</li>`:''}</ul>
  ${plan.materials?.length?`<details style="margin-top:8px"><summary class="muted" style="cursor:pointer">每份材料的用途（${plan.materials.length}）</summary><ul class="rule-list">${plan.materials.map(m=>`<li>${e(m.file)}：${e(m.use)}</li>`).join('')}</ul></details>`:''}`;
}

function understandQuestion(t,p) {
  const plan=p.plan,n=plan.questions.length;
  return `<form id="confirm-form" data-kind="understand"><div class="notice amber">开始处理前，还需要你补充 <b>${n}</b> 处信息。补上后自动开始；拿不准的可以先空着，处理完会再提醒你。</div>
  <section class="card"><div class="card-body review-area">${plan.questions.map((q,i)=>`<section class="review-card" data-question="${i}">
  <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 10px;align-items:baseline"><span class="review-number">${i+1}</span><div><b>问题：</b>${e(q.question)}</div>${q.need||q.why?`<span></span><div><b>需要：</b>${e(q.need||q.why)}</div>`:''}</div>
  <div style="display:flex;flex-direction:column;gap:6px;margin:10px 0 0 34px">${q.options.map(o=>`<label class="check"><input type="radio" name="q${i}" value="${e(o)}"> ${e(o)}</label>`).join('')}<input type="text" data-other maxlength="300" placeholder="${q.options.length?'或者直接写':'直接写在这里'}"></div></section>`).join('')}
  <details style="margin-top:4px"><summary class="muted" style="cursor:pointer">还有别的要说明（可不填）</summary><textarea data-note maxlength="1000" rows="2" style="margin-top:6px;width:100%"></textarea></details></div></section>
  <details class="card"><summary class="card-head" style="cursor:pointer"><h2>系统目前对规则的理解</h2><small class="muted">一般不用看，想核对时展开</small></summary><div class="card-body">${planBody(plan)}</div></details>
  <div class="review-submit"><small>补充的内容会附在规则后面，后续都按它处理。</small><button class="button primary" type="submit">补充好了，开始处理 ${icon('arrow')}</button></div></form>`;
}

const MATERIAL_STATUS={imported:['已导入','green'],roster:['名单','green'],rules:['评分规则','green'],duplicate:['重复，已忽略','amber'],empty:['没有成绩','amber'],skipped:['未处理','red'],failed:['没读出来','red']};
function materialsSection(list) {
  if(!list?.length) return '';
  const bad=list.filter(m=>!['imported','roster','rules'].includes(m.status)).length;
  return `<details class="card" ${bad?'open':''}><summary class="card-head" style="cursor:pointer"><h2>材料清单</h2><small class="muted">${list.length} 份${bad?` · <b style="color:var(--amber)">${bad} 份需要留意</b>`:' · 全部已读取'}</small></summary><div class="card-body"><ul class="rule-list" style="list-style:none;padding:0">${list.map(m=>`<li>${badge(...(MATERIAL_STATUS[m.status]||[m.status,'']))} <b>${e(m.name)}</b> <small class="muted">${e(m.text)}</small></li>`).join('')}</ul></div></details>`;
}

// ---------------------------------------------------------------- course confirmation
function ruleSection(p) {
  const lines=(p.rule_lines||[]).map((x,i)=>`<li><span class="review-number" style="display:inline-grid;width:22px;height:22px;font-size:12px;margin-right:6px">${i+1}</span>${e(x)}</li>`).join('');
  return `<div class="card-head"><h2>我是这样理解你的规则的</h2>${p.errors?.length?badge('需要修改','red'):badge('请核对','amber')}</div><div class="card-body">
  ${p.source_text?(p.source_text.length>150?`<details style="margin-bottom:12px"><summary class="muted" style="cursor:pointer">你写的规则原文（${p.source_text.length} 字，点击展开）</summary><pre class="code-box" style="white-space:pre-wrap">${e(p.source_text)}</pre></details>`:`<p class="muted" style="margin-bottom:12px">你写的是：“${e(p.source_text)}”</p>`):''}
  ${p.rule?.template?`<div class="notice" style="margin-bottom:12px">沿用规则模板“${e(p.rule.template)}”（以前确认过的版本），没有重新理解规则；下面的检查是按这次的数据做的，项目对不上会提示。</div>`:''}
  ${p.rule?.fallback?`<div class="notice amber" style="margin-bottom:12px">模型这次没有给出可用的规则理解（服务繁忙或返回为空），下面只是按数据列出的项目。<button class="button small" type="button" data-action="reparse" style="margin-left:8px">重新理解规则</button></div>`:''}
  <ul class="rule-list" style="list-style:none;padding:0">${lines}</ul>
  <div class="form-help" style="margin-top:8px">总评保留 <select data-digits style="width:auto;display:inline-block;padding:2px 6px">${[0,1,2,3,4].map(n=>`<option value="${n}" ${p.rule?.rounding?.digits===n?'selected':''}>${n}</option>`).join('')}</select> 位小数（四舍五入）</div>
  ${p.errors?.length?`<div class="notice red" style="margin-top:12px">${p.errors.map(e).join('<br>')}</div>`:''}
  ${p.unclear?.length?`<div class="notice amber" style="margin-top:12px"><b>请留意</b><ul class="rule-list">${p.unclear.map(x=>`<li>${e(x)}</li>`).join('')}</ul></div>`:''}
  ${(p.revisions||[]).length?`<div class="form-help" style="margin-top:10px">已按你的话修改：${p.revisions.map(r=>`“${e(r.text)}”`).join('、')}</div>`:''}
  <div class="form-actions" style="margin-top:14px"><input type="text" id="revise-text" maxlength="500" placeholder="哪里不对，直接说：如“期中改成30%，期末改成40%”" style="flex:1"><button class="button" type="button" data-action="revise">修改</button></div></div>`;
}

function previewSection(p) {
  const rows=p.preview||[];
  if(!rows.length) return p.rule?`<div class="card-head"><h2>结果预览</h2></div><div class="card-body"><p class="muted">规则修改好以后，这里会显示每个人的总评。</p></div>`:'';
  const comps=rows[0].components.map(c=>c.name);
  const counts={ok:0,pending:0,invalid:0,exempt:0};rows.forEach(r=>counts[r.outcome]++);
  return `<div class="card-head"><h2>按这个规则，结果是这样的</h2><small class="muted">${rows.length} 人 · 已算出 ${counts.ok} 人${counts.pending?` · 待定 ${counts.pending}`:''}${counts.invalid?` · 无效 ${counts.invalid}`:''}${counts.exempt?` · 免修 ${counts.exempt}`:''}</small></div>${zeroNotice(p)}<div class="table-wrap"><table><thead><tr><th>学号 / 姓名</th>${comps.map(c=>`<th>${e(c)}</th>`).join('')}<th>总评</th><th>说明</th></tr></thead><tbody>${rows.slice(0,80).map(r=>`<tr><td><div class="mono">${e(r.student_id)}</div><small class="muted">${e(r.student_name)}</small></td>${r.components.map(c=>`<td>${c.percent??'<span class="muted">—</span>'}</td>`).join('')}<td>${r.total==null?outcomeBadge(r.outcome):`<strong style="color:${r.total<60?'var(--red)':'var(--ink)'}">${r.total}</strong>`}</td><td style="white-space:normal;min-width:200px"><small class="muted">${e(r.notes.join('；'))}</small></td></tr>`).join('')}</tbody></table></div>${p.issues?.length?'<div class="table-note">上面问题中涉及的记录，决定之后才会计入。</div>':''}`;
}

// 0 is a sensitive number: every 0 the rule produces is listed with its reason; it can still be changed after the result is out.
function zeroNotice(p) {
  const pick=pending=>(p.zeros||[]).map(z=>({...z,items:z.items.filter(i=>!!i.pending===pending)})).filter(z=>z.items.length);
  const zeros=pick(false),waits=pick(true),mism=p.mismatches||[],count=zeros.reduce((s,z)=>s+z.items.length,0);
  const list=group=>`<ul class="rule-list" style="margin-top:8px">${group.map(z=>`<li><span class="mono">${e(z.student_id)}</span> ${e(z.student_name)}：${z.items.map(item=>`${e(item.text)}${(item.fill||[]).map(f=>` <input type="text" data-fill='${e(JSON.stringify({student_id:z.student_id,assessment:f.assessment,occurrence:f.occurrence}))}' maxlength="20" placeholder="补录${e((f.occurrence||f.assessment).split('·').pop())}${item.pending?'':'（留空按0分）'}" style="width:150px;display:inline-block;padding:2px 6px">`).join('')}`).join('；')}</li>`).join('')}</ul>`;
  return `${count?`<details class="notice amber" style="margin:12px 18px" ${count<=12?'open':''}><summary style="cursor:pointer"><b>有 ${count} 处是 0 分，请确认</b>（${zeros.length} 人；没有记录、缺考、未交都按 0 分计。原本有成绩只是没导出的，可以直接在后面补录；确认后在结果里仍可修改）</summary>${list(zeros)}</details>`:''}
  ${waits.length?`<details class="notice" style="margin:12px 18px" open><summary style="cursor:pointer"><b>${waits.length} 人有缺失记录，总评暂时待定</b>（规则没说没有记录按 0 分，所以不当 0 分；可以在后面补录，或在规则下方说“没有记录按 0 分”）</summary>${list(waits)}</details>`:''}
  ${mism.length?`<details class="notice" style="margin:12px 18px"><summary style="cursor:pointer"><b>${mism.length} 人的平台导出总评与按分项重算不一致</b>，已按重算值计入</summary><ul class="rule-list" style="margin-top:8px">${mism.map(z=>`<li><span class="mono">${e(z.student_id)}</span> ${e(z.student_name)}：${z.items.map(e).join('；')}</li>`).join('')}</ul></details>`:''}
  ${(p.remark_commands||[]).length?`<details class="notice amber" style="margin:12px 18px" open><summary style="cursor:pointer"><b>${p.remark_commands.length} 条原始记录的备注里有像算分指令的文字</b>，系统只把它当作数据，没有照做；算分只依据你写的规则</summary><ul class="rule-list" style="margin-top:8px">${p.remark_commands.map(x=>`<li>${e(x)}</li>`).join('')}</ul></details>`:''}
  ${(p.outside||[]).length?`<details class="notice" style="margin:12px 18px"><summary style="cursor:pointer"><b>${p.outside.length} 处记录不属于 ${e(p.scope||'本课程本学期')}，未计入</b>（其他课程或学期混进来的，不对可以在上面用一句话修改规则）</summary><ul class="rule-list" style="margin-top:8px">${p.outside.map(o=>`<li>${e(o.text)}</li>`).join('')}</ul></details>`:''}`;
}

function issueCard(issue,i) {
  const s=issue.suggestion,cands=issue.candidates||[],scope=issue.scope||'row';
  let options;
  if(issue.type==='conflict') options=issue.options.map(o=>[`select:${o.value}`,`采用 ${o.label}`]).concat([['exclude','都不采用']]);
  else if(issue.type==='duplicate') options=issue.options.map(o=>[`select:${o.value}`,o.label]).concat([['keep','不是同一次，都计入']]);
  else options=[['correct',scope==='value'?'改成：':scope==='identity'?'是这位学生：':'改成：'],...(/名单|不一致|识别不确定/.test(issue.title)?[['accept','原记录没错，保留']]:[]),['exclude','不计入']];
  const chosen=s?.action||'';
  const idInput=issue.type==='row'&&scope!=='value'?`<select data-correct-id>${cands.map(c=>`<option value="${e(c.student_id)}" ${s?.student_id===c.student_id?'selected':''}>${e(c.student_id)} ${e(c.student_name)}</option>`).join('')}<option value="" ${cands.length?'':'selected'}>其他（下面填写）</option></select><input type="text" data-correct-id-text placeholder="填写学号" value="${e(cands.length?'':issue.record?.student_id||'')}" ${cands.length?'hidden':''}>`:'';
  const scoreInput=issue.type==='row'&&scope!=='identity'?`<input type="text" data-correct-score value="${e(issue.record?.raw_score??'')}" placeholder="正确的分数或状态">`:'';
  const sources=[...new Map((issue.record?[issue.record]:issue.records||[]).flatMap(r=>r.sources||[r.source]).filter(Boolean).map(x=>[`${x.file}|${x.sheet}|${x.row}`,x])).values()];
  return `<section class="review-card" data-issue="${e(issue.id)}"><div class="review-head"><span class="review-number">${i+1}</span><div><strong>${e(issue.title)}</strong><small>${e(issue.description)}</small>${issue.was?`<small style="color:var(--amber)">之前选的“${e(issue.was)}”已失效：材料变了，请重新决定</small>`:''}${sources.length?`<small>${sources.slice(0,4).map(x=>locateButton(x)).join(' ')}</small>`:''}</div>${s?badge('已按建议预选','green'):badge('需要你选','amber')}</div>
  <div class="review-selects"><select data-choice aria-label="处理方式"><option value="" ${chosen?'':'selected'}>请选择…</option>${options.map(([v,l])=>`<option value="${e(v)}" ${v===chosen?'selected':''}>${e(l)}${s&&v===chosen?'（建议）':''}</option>`).join('')}</select><span class="row-correction" ${chosen==='correct'?'':'hidden'} style="display:${chosen==='correct'?'flex':'none'};gap:8px">${idInput}${scoreInput}</span></div>${s?`<small class="muted">建议：${e(s.label)}</small>`:''}</section>`;
}

function assumptionsSection(p) {
  const fields=[['student_id','学号'],['student_name','姓名'],['course_name','课程'],['assessment','考核项目'],['occurrence','次序/日期'],['score','成绩'],['remark','备注']];
  return `<details class="card"><summary class="card-head" style="cursor:pointer"><h2>系统对每份材料的理解</h2><small class="muted">${p.tables.length} 张表 · 名单 ${p.roster_size||0} 人 · 去重 ${p.summary?.duplicate_rows??0} 条 · 一般不用看，不对可以改</small></summary><div class="card-body">${p.tables.map(t=>`<div class="review-card" data-table="${e(t.id)}" data-mapping='${e(JSON.stringify(t.mapping))}'><div class="review-head"><span class="review-number">${icon(t.origin==='image'?'file':'table')}</span><div><strong>${e(t.name)} · ${t.rows} 行</strong><small>${e(t.text)}</small>${t.notes.map(n=>`<small>${e(n)}</small>`).join('')}</div></div><details><summary><small class="muted">修改这张表的理解</small></summary><div class="rule-card" style="margin-top:8px">${fields.map(([k,l])=>`<label class="rule-field"><span>${l}</span><select data-field="${k}"><option value="">没有</option>${t.headers.map(h=>`<option value="${e(h)}" ${t.mapping[k]===h?'selected':''}>${e(h)}</option>`).join('')}</select></label>`).join('')}</div><div class="form-help">每列一次考核的列：${t.headers.map(h=>`<label class="check"><input type="checkbox" data-item value="${e(h)}" ${(t.mapping.item_columns||[]).includes(h)?'checked':''}>${e(h)}</label>`).join(' ')}</div></details></div>`).join('')}
  ${p.missing_students?.length?`<div class="notice amber">名单中有 ${p.missing_students.length} 人没有任何记录：${p.missing_students.map(m=>e(m.student_id+' '+m.student_name)).join('、')}</div>`:''}</div></details>`;
}

function gradesConfirm(t,p) {
  const issues=p.issues||[],open=issues.filter(i=>!i.suggestion).length;
  const failed=p.failed_files||[];
  return `<form id="confirm-form" data-kind="grades">
  ${failed.length?`<div class="notice red"><b>${failed.length} 份文件没有读出来：</b>${failed.map(f=>`${e(f.name)}（${e(f.error)}）`).join('；')}。这些文件里的成绩没有计入，下面的“没有记录”可能是因此造成的，不一定是学生真的没交。</div>`:''}
  <div class="notice">${p.rule?'请核对规则和结果，':''}${issues.length?`有 <b>${issues.length}</b> 个问题需要决定${open?`，其中 ${open} 个需要你选，其余已按建议预选`:'，都已按建议预选'}。`:'没有发现需要你决定的问题。'}确认后生成最终结果，每个分数都能查到来源。</div>
  ${p.plan&&!p.plan.skipped?`<details class="card"><summary class="card-head" style="cursor:pointer"><h2>开始前的理解</h2><small class="muted">考核对象、完整性依据${p.plan.answers?.some(Boolean)?'和你的补充说明':''}</small></summary><div class="card-body">${planBody(p.plan)}</div></details>`:''}
  ${materialsSection(p.materials)}
  ${p.rule?`<section class="card" id="rule-section">${ruleSection(p)}</section>`:''}
  ${issues.length?`<section class="card"><div class="card-head"><h2>需要你决定的问题</h2><small class="muted">${issues.length} 个</small></div><div class="card-body review-area">${issues.map(issueCard).join('')}</div></section>`:''}
  ${(p.decided||[]).length?`<details class="card"><summary class="card-head" style="cursor:pointer"><h2>已经处理过的问题</h2><small class="muted">${p.decided.length} 个 · 处理错了可以撤回，撤回后会重新问你</small></summary><div class="card-body"><ul class="rule-list" style="list-style:none;padding:0">${p.decided.map(d=>`<li style="display:flex;gap:10px;align-items:baseline"><span style="flex:1"><b>${e(d.title)}</b> <small class="muted">${e(d.description)}</small><br>→ ${e(d.label)}</span><button class="button ghost small" type="button" data-revoke="${e(d.id)}">撤回</button></li>`).join('')}</ul></div></details>`:''}
  ${p.rule?`<section class="card" id="preview-section">${previewSection(p)}</section>`:''}
  ${assumptionsSection(p)}
  <div class="review-submit"><small>确认后由程序按规则精确计算，并导出结果与依据。<a class="settings-link" href="/api/tasks/${t.id}/download/results.xlsx">下载暂定结果（Excel，未确认）</a></small><button class="button primary" type="submit">确认，生成结果 ${icon('arrow')}</button></div></form>`;
}

// ---------------------------------------------------------------- appraisal confirmation
function schemeSection(p) {
  return `<div class="card-head"><h2>我是这样理解考核方案的</h2>${p.errors?.length?badge('需要修改','red'):badge('请核对','amber')}</div><div class="card-body">
  <ul class="rule-list" style="list-style:none;padding:0">${(p.scheme_lines||[]).map((x,i)=>`<li><span class="review-number" style="display:inline-grid;width:22px;height:22px;font-size:12px;margin-right:6px">${i+1}</span>${e(x)}</li>`).join('')}</ul>
  ${p.errors?.length?`<div class="notice red" style="margin-top:12px">${p.errors.map(e).join('<br>')}</div>`:''}
  ${p.warnings?.length?`<div class="notice amber" style="margin-top:12px">${p.warnings.map(e).join('<br>')}</div>`:''}
  ${p.unclear?.length?`<div class="notice amber" style="margin-top:12px"><b>方案没说清的地方</b><ul class="rule-list">${p.unclear.map(x=>`<li>${e(x)}</li>`).join('')}</ul></div>`:''}
  ${p.scheme_changed?'<div class="notice" style="margin-top:12px">指标已按你的话修改。确认后会按新指标重新整理材料（约一分钟），然后再请你打分。</div>':''}
  <details style="margin-top:10px"><summary><small class="muted">方案原文</small></summary><pre class="code-box" style="white-space:pre-wrap">${e(p.source_text)}</pre></details>
  <div class="form-actions" style="margin-top:14px"><input type="text" id="revise-text" maxlength="500" placeholder="哪里不对，直接说：如“科技讲座每次计3分，最高12分”" style="flex:1"><button class="button" type="button" data-action="revise">修改</button></div></div>`;
}

const MATERIAL_STATES={needs_proof:['需要补充证明','amber'],ineligible:['不符合条件','red'],judge:['待人工评分','blue'],counted:['可以计分','green']};
function materialRow(t,m,p) {
  const st=MATERIAL_STATES[m.status]||['',''],open=['needs_proof','ineligible'].includes(m.status)&&!m.excluded;
  return `<tr data-material="${e(m.id)}"${m.status==='needs_proof'?' style="background:var(--amber-soft)"':''}><td style="white-space:normal;min-width:180px">${st[0]?badge(st[0],st[1])+'<br>':''}${sourceLink(t,m)}<br><small class="muted">${e(m.doc_type)}${m.level?' · '+e(m.level):''}${m.date?' · '+e(m.date):''}${m.role?' · '+e(m.role):''}${m.project?' · '+e(m.project):''}</small></td><td style="white-space:normal;min-width:240px"><div>${e(m.summary)}</div>${(m.reasons||[]).map(f=>`<div><small style="color:${m.status==='counted'?'var(--teal)':m.status==='judge'?'var(--ink)':'var(--amber)'}">${m.status==='counted'?'✓':'•'} ${e(f)}</small></div>`).join('')}${(m.uncertain||[]).filter(u=>!(m.reasons||[]).includes(u)).map(u=>`<div><small class="muted">模型的疑问：${e(u)}</small></div>`).join('')}${quoteList(m.quotes)}</td>
  <td style="min-width:210px"><div style="display:grid;gap:6px"><select data-k="person"><option value="">未确定</option>${p.people.map(x=>`<option ${m.person===x?'selected':''}>${e(x)}</option>`).join('')}</select><select data-k="indicator"><option value="">不对应任何指标</option>${p.scheme.indicators.map(i=>`<option value="${e(i.id)}" ${m.indicator===i.id?'selected':''}>${e(i.name)}</option>`).join('')}</select>${open||m.accepted?`<label class="check"><input type="checkbox" data-k="accepted" ${m.accepted?'checked':''}>已核实，计分</label>`:''}<label class="check"><input type="checkbox" data-k="excluded" ${m.excluded?'checked':''}>不计入</label><input type="text" data-k="note" placeholder="核实情况或不计入的原因" maxlength="300" value="${e(m.note||'')}"><details${m.flags.some(f=>f.startsWith('材料类型')||f.startsWith('级别'))?' open':''}><summary><small class="muted">修正识别结果</small></summary><div style="display:grid;gap:6px;margin-top:6px"><input type="text" data-k="doc_type" value="${e(m.doc_type)}" maxlength="40" placeholder="材料类型"><input type="text" data-k="level" value="${e(m.level)}" maxlength="30" placeholder="级别，如省级"><input type="text" data-k="project" value="${e(m.project)}" maxlength="120" placeholder="项目/论文题目（相同的合并为 1 项）"></div></details></div></td></tr>`;
}

// Which materials are the same achievement: both side by side, who decided it and on what evidence; every one can be changed.
const PAIR_FIELDS=[['cert_no','编号'],['contest','比赛'],['edition','届次'],['project','作品/题目'],['award','获奖等级'],['level','级别'],['students','学生'],['date','日期']];
function relationsSection(t,p) {
  const list=p.relations||[];
  if(!list.length)return '';
  const by={rule:['程序规则',''],model:['模型判断','blue'],evaluator:['你改过','green'],none:['模型没有判断','amber']};
  const open=list.filter(r=>r.relation==='unsure').length;
  const row=r=>{const [a,b]=r.pair;return `<tr data-relation-row="${e(r.key)}"${r.relation==='unsure'?' style="background:var(--amber-soft)"':''}><td style="white-space:normal;min-width:330px"><table style="font-size:13px"><thead><tr><th></th><th>${a.index!=null?sourceLink(t,{index:a.index,file:a.file}):e(a.file)}</th><th>${b.index!=null?sourceLink(t,{index:b.index,file:b.file}):e(b.file)}</th></tr></thead><tbody>${PAIR_FIELDS.filter(([k])=>a[k]||b[k]).map(([k,l])=>`<tr><td class="muted">${l}</td><td>${e(a[k])}</td><td>${e(b[k])}</td><td>${a[k]&&b[k]?(a[k]===b[k]?'<span style="color:var(--teal)">✓</span>':'<span style="color:var(--amber)">✗</span>'):''}</td></tr>`).join('')}</tbody></table></td>
  <td style="white-space:normal;min-width:260px"><select data-relation="${e(r.key)}" data-was="${e(r.relation)}">${Object.entries(p.relation_words).map(([k,l])=>`<option value="${k}" ${r.relation===k?'selected':''}>${e(l)}</option>`).join('')}</select><div style="margin-top:6px">${badge(...(by[r.by]||[r.by,'']))} <small>${e(r.reason)}</small></div>${quoteList(r.evidence)}</td></tr>`;};
  return `<section class="card"><div class="card-head"><h2>可能重复的材料</h2><small class="muted">${list.length} 组 · 证据确定的由程序判断，其余由模型判断并给出原文依据，都可以改${open?` · <b style="color:var(--amber)">${open} 组需要你判断</b>`:''}</small></div><div class="table-wrap"><table><tbody>${list.map(row).join('')}</tbody></table></div></section>`;
}
function schemeQuestions(p) {
  return (p.questions||[]).map(q=>`<section class="review-card" data-scheme-question="${e(q.id)}"><div><b>问题：</b>${e(q.question)}</div><div><b>需要：</b>${e(q.need)}</div><div style="display:flex;flex-direction:column;gap:6px;margin-top:8px">${Object.entries(q.options).map(([k,l])=>`<label class="check"><input type="radio" name="sq-${e(q.id)}" value="${k}"> ${e(l)}</label>`).join('')}</div></section>`).join('');
}

function appraisalConfirm(t,p) {
  if(p.scheme_changed) return `<form id="confirm-form" data-kind="appraisal"><section class="card" id="rule-section">${schemeSection(p)}</section><div class="review-submit"><small>确认后按新指标重新整理材料。</small><button class="button primary" type="submit">按新指标重新整理 ${icon('arrow')}</button></div></form>`;
  const byState=k=>p.materials.filter(m=>(m.status||'counted')===k),proof=byState('needs_proof');
  const toScore=p.judge.filter(j=>!j.decided),byPerson=p.people.map(person=>[person,toScore.filter(j=>j.person===person)]).filter(([,list])=>list.length);
  const table=list=>`<div class="table-wrap"><table><thead><tr><th>材料</th><th>读到的内容</th><th>归属 / 指标</th></tr></thead><tbody>${list.map(m=>materialRow(t,m,p)).join('')}</tbody></table></div>`;
  const judgeRow=j=>{const s=j.suggestion,value=j.decided?.score??'';return `<tr data-judge="${e(j.key)}"><td style="white-space:normal;min-width:150px"><b>${e(j.name)}</b><br><small class="muted">0 – ${j.max} 分${j.materials.length?` · ${j.materials.length} 份材料`:' · 没有对应材料'}</small><br><small class="muted">要评价工作质量或效果，系统不能代你打分</small></td><td style="min-width:120px"><input type="number" data-k="score" min="0" max="${j.max}" step="0.5" value="${e(value)}" placeholder="0 – ${j.max}">${s&&s.score!=null?`<button class="button ghost small" type="button" data-use-suggestion="${s.score}" style="margin-top:4px">采用建议 ${s.score} 分</button>`:''}</td><td style="white-space:normal;min-width:320px">${s&&s.score!=null?`<div>模型建议<b>${e(s.level)}</b>（${s.score} 分），仅供参考</div><details><summary><small class="muted">依据</small></summary><small>${e(s.reason)}</small>${s.missing?`<div><small style="color:var(--amber)">材料不足：${e(s.missing)}</small></div>`:''}${quoteList(s.quotes)}</details>`:`<small class="muted">${j.has_criteria?e(s?.reason||'没有对应材料，请直接评价。'):'方案没有给出评价标准，请你直接打分；系统只整理了材料。'}</small>`}<div class="quote-line"><small>${j.materials.map(id=>p.materials.find(m=>m.id===id)).filter(Boolean).map(m=>sourceLink(t,m)).join('、')}</small></div><input type="text" data-k="note" placeholder="说明（可选）" maxlength="300" style="margin-top:6px"></td></tr>`;};
  const preview=p.preview||[];
  return `<form id="confirm-form" data-kind="appraisal">
  <div class="notice">${p.people.length} 人、${p.materials.length} 份材料已整理完毕：${Object.entries(MATERIAL_STATES).map(([k,[l,c]])=>`${badge(l+' '+byState(k).length,c)}`).join(' ')}<br>${proof.length?`<b>${proof.length}</b> 份材料需要补充证明或核实，请逐份决定“已核实，计分”或“不计入”；`:''}${toScore.length?`<b>${toScore.length}</b> 项评价类指标需要你打分（模型建议只供参考，不会自动填入）；`:''}可以计分的材料由程序按方案算分。</div>
  <section class="card" id="rule-section">${schemeSection(p)}</section>
  ${(p.questions||[]).length?`<section class="card"><div class="card-head"><h2>方案没说清的计分方式</h2>${badge('请选择','amber')}</div><div class="card-body review-area">${schemeQuestions(p)}</div></section>`:''}
  ${relationsSection(t,p)}
  ${toScore.length?`<section class="card"><div class="card-head"><h2>需要你打分</h2><small class="muted">${toScore.length} 项 · 建议只依据方案中的标准和材料原文</small></div><div class="card-body review-area">${byPerson.map(([person,list])=>`<section class="review-card"><div class="review-head"><span class="review-number">${e(person.slice(0,1))}</span><div><strong>${e(person)}</strong></div></div><div class="table-wrap"><table><tbody>${list.map(judgeRow).join('')}</tbody></table></div></section>`).join('')}</div></section>`:''}
  ${proof.length?`<section class="card"><div class="card-head"><h2>需要补充证明的材料</h2><small class="muted">${proof.length} 份 · 材料没写清，系统不能直接计分</small></div>${table(proof)}</section>`:''}
  ${[['ineligible','不符合条件的材料','按材料写的内容不满足方案条件，不计分；判断错了可以改为“已核实，计分”'],['judge','待人工评分的材料','对应评价类指标，请在上面打分时参考'],['counted','可以计分的材料','满足方案条件，由程序计分']].map(([k,title,sub])=>byState(k).length?`<details class="card"${k==='ineligible'?' open':''}><summary class="card-head" style="cursor:pointer"><h2>${title}</h2><small class="muted">${byState(k).length} 份 · ${sub}</small></summary>${table(byState(k))}</details>`:'').join('')}
  ${preview.length?`<section class="card"><div class="card-head"><h2>目前的得分</h2><small class="muted">评价类按建议分暂计，以你确认的分数为准</small></div><div class="table-wrap"><table><thead><tr><th>被考核人</th><th>合计</th>${p.scheme.indicators.map(i=>`<th>${e(i.name)}<br><small class="muted">${i.max}</small></th>`).join('')}</tr></thead><tbody>${preview.map(r=>`<tr><td>${e(r.person)}</td><td><strong>${r.total??r.partial}</strong>${r.total==null?' <small class="muted">（未完）</small>':''}</td>${r.items.map(i=>`<td>${i.score??'<span class="muted">—</span>'}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>`:''}
  <div class="review-submit"><small>确认后导出汇总表和每个人的评分依据。<a class="settings-link" href="/api/tasks/${t.id}/download/results.xlsx">下载暂定结果（Excel，未确认）</a></small><button class="button primary" type="submit">确认，生成结果 ${icon('arrow')}</button></div></form>`;
}

// ---------------------------------------------------------------- results
function resultPage(t) {
  const current=['result','basis','trace','sources'].includes(state.tab)?state.tab:'result';
  const downloads=t.kind==='appraisal'?[['results.xlsx','结果（Excel）'],['summary.csv','评分汇总表'],['report.html','评分依据报告'],['audit.json','完整证据']]:[['results.xlsx','结果（Excel：总评、问题清单、规则、材料目录）'],...(t.result.totals?[['totals.csv','课程总评表']]:[]),['grades.csv','整合记录表'],['report.html','任务报告'],['audit.json','完整证据']];
  return `${t.kind==='appraisal'?appraisalStats(t):taskStats(t)}<div class="button-row" style="margin:0 0 16px">${downloads.map(([f,l],i)=>`<a class="button small ${i===0?'primary':''}" href="/api/tasks/${t.id}/download/${f}">${icon('download')}${l}</a>`).join('')}${t.result.rule||t.result.scheme?'<button class="button ghost small" type="button" data-action="save-template">保存为规则模板</button>':''}</div>
  <section class="card"><div class="tabs">${[['result','结果'],['basis','计算依据'],['trace','处理记录'],['sources','原始材料']].map(([key,label])=>`<button class="tab ${current===key?'active':''}" data-tab="${key}">${label}</button>`).join('')}</div>${current==='result'?(t.kind==='appraisal'?appraisalResult(t):resultView(t)):current==='basis'?basisView(t):current==='trace'?traceView(t):sourceView(t)}</section>`;
}

function basisView(t) {
  const r=t.result;
  if(t.kind==='appraisal') return `<div class="card-body"><h3>考核指标（已确认）</h3><ul class="rule-list">${r.scheme.indicators.map(i=>`<li>${e(i.group)} / ${e(i.name)}：${i.max} 分 · ${e(state.config.methods[i.method])}</li>`).join('')}</ul></div>`;
  return `<div class="card-body">${r.rule_lines?`<h3>评分规则（已确认）</h3><ul class="rule-list">${r.rule_lines.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`:''}<h3 style="margin-top:16px">每份材料的理解</h3><ul class="rule-list">${(r.tables||[]).map(x=>`<li><b>${e(x.name)}</b>（${x.rows} 行）：${e(x.text)}${x.notes.length?`<br><small class="muted">${e(x.notes.join('；'))}</small>`:''}</li>`).join('')}</ul>${r.plan&&!r.plan.skipped?`<h3 style="margin-top:16px">开始前的理解</h3>${planBody(r.plan)}`:''}${r.materials?.length?`<h3 style="margin-top:16px">材料清单</h3><ul class="rule-list">${r.materials.map(m=>`<li>${e((MATERIAL_STATUS[m.status]||[m.status])[0])} · <b>${e(m.name)}</b> <small class="muted">${e(m.text)}</small></li>`).join('')}</ul>`:''}<h3 style="margin-top:16px">处理口径</h3><ul class="rule-list">${(r.rules||[]).map(x=>`<li>${e(x)}</li>`).join('')}</ul></div>`;
}

function taskStats(task) {
  const s=task.result.summary||{},ts=task.result.totals_summary;
  if(ts) return `<div class="stats">${stat('整合记录',s.output_rows??'—',`${task.files.length} 份材料 · 去重 ${s.duplicate_rows??0} 条`,'table')}${stat('总评已算出',ts.computed,'按你确认的规则','check','teal')}${stat('总评待定 / 无效',(ts.pending||0)+(ts.invalid||0),'缓考、缺考试成绩等','alert','amber')}${stat('名单',s.roster_size||0,s.name_matched?`${s.name_matched} 条按名单认人`:'人','list')}</div>`;
  return `<div class="stats">${stat('输入记录',s.input_rows??'—',`${task.files.length} 份材料`,'table')}${stat('整合后',s.output_rows??'—','每条保留全部来源','check','teal')}${stat('去掉重复',s.duplicate_rows??'—','同一次考核的重复记录','list')}${stat('冲突',s.conflict_groups??0,'已由你选定','alert','amber')}</div>`;
}

function appraisalStats(t) {
  const r=t.result,s=r.summary||{};
  return `<div class="stats">${stat('被考核人',s.people,'全部已出总分','list')}${stat('证明材料',s.materials,`不计入 ${s.excluded||0} 份`,'file')}${stat('重复材料合并',s.merged||0,'同一项目多份证书计 1 项','check','teal')}${stat('建议分被采用',`${r.agreement?.kept??0} / ${r.agreement?.suggested??0}`,'你的分数与建议一致的次数','spark','amber')}</div>`;
}

const outcomeBadge = o => ({ok:'',pending:badge('待定','amber'),invalid:badge('无效','red'),exempt:badge('免修','blue')}[o]||'');
const cellScore = r => r.status?badge(r.status,'amber'):r.mark?'√ <small class="muted">记一次</small>':`<strong style="color:${r.score<60?'var(--red)':'var(--ink)'}">${r.score}</strong>`;

function resultView(task) {
  const rows=task.result.rows||[],totals=task.result.totals;
  if(!rows.length) return empty('结果正在形成',task.status==='waiting_review'?'请先处理待复核项目，确定后会更新结果。':'处理过程中可在“执行记录”查看当前步骤。');
  const missing=task.result.missing_students||[];
  const warn=missing.length?`<div class="notice amber">课程名单中有 ${missing.length} 名学生没有任何成绩记录：${missing.map(m=>`${e(m.student_id)} ${e(m.student_name)}`).join('、')}。请确认是否漏记、退课或另有安排。</div>`:'';
  const view=totals&&state.resultView!=='records'?'totals':'records';
  const switcher=totals?`<div class="filters" style="margin-bottom:12px"><button class="filter ${view==='totals'?'active':''}" data-view="totals">课程总评 · ${totals.length}</button><button class="filter ${view==='records'?'active':''}" data-view="records">整合后的考核记录 · ${rows.length}</button></div>`:'';
  if(view==='totals') {
    const comps=task.result.rule.components,s=task.result.totals_summary||{};
    const table=`<table><thead><tr><th>学号 / 姓名</th>${comps.map(c=>`<th>${e(c.name)}<br><small class="muted">${c.weight}%</small></th>`).join('')}<th>总评</th><th>说明</th><th>依据</th></tr></thead><tbody>${totals.map((t,i)=>`<tr><td><div class="mono">${e(t.student_id)}</div><small class="muted">${e(t.student_name)}</small></td>${t.components.map(p=>`<td>${p.percent==null?'<span class="muted">—</span>':p.percent}</td>`).join('')}<td>${t.total==null?outcomeBadge(t.outcome):`<strong style="color:${t.total<60?'var(--red)':'var(--ink)'}">${t.total}</strong>`}</td><td style="white-space:normal;min-width:220px;max-width:360px"><small class="muted">${e(t.notes.join('；'))}${t.resits.length?`<br>补考：${t.resits.map(r=>e(r.assessment+' '+r.shown)).join('、')}`:''}</small></td><td><button class="button ghost small" data-total-row="${i}">计算过程 ↗</button></td></tr>`).join('')}</tbody></table>`;
    return `${switcher}${warn}<div class="result-intro"><span>已计算 ${s.computed??0} 人，待定 ${s.pending??0} 人${s.invalid?`，无效 ${s.invalid} 人`:''}${s.exempt?`，免修 ${s.exempt} 人`:''}。各组成项为百分制得分。</span><span>${totals.length} 名学生</span></div><div class="table-wrap">${table}</div>`;
  }
  const table=`<table><thead><tr><th>学号 / 姓名</th><th>课程</th><th>考核 / 次序 / 批次</th><th>成绩</th><th>来源</th><th>依据</th></tr></thead><tbody>${rows.slice(0,200).map((r,i)=>`<tr><td><div class="mono">${e(r.student_id)}</div><small class="muted">${e(r.student_name)}${r.matched_by?' · 按名单认人':''}</small></td><td><div>${e(r.course_name||r.course_id)}</div><small class="mono muted">${e(r.course_id)}</small></td><td>${e(r.assessment)}${r.occurrence?` <small class="muted">${/^\d+$/.test(r.occurrence)?'第'+e(r.occurrence)+'次':e(r.occurrence)}</small>`:''}<br><small class="muted">${e(r.attempt)} · ${e(r.term)}</small></td><td>${cellScore(r)}</td><td>${r.source_count} 处${r.reviewed?' '+badge('已复核','green'):''}</td><td><button class="button ghost small" data-evidence-row="${i}">查看来源 ↗</button></td></tr>`).join('')}</tbody></table>`;
  return `${switcher}${warn}<div class="result-intro"><span>每项成绩保留全部来源；不同考核项目、次序和批次独立显示。</span><span>${rows.length} 条记录</span></div><div class="table-wrap">${table}</div>${rows.length>200?'<div class="table-note">页面显示前200条，导出包含全部已确定记录。</div>':''}`;
}

function openTotal(index) {
  const t=state.task.result.totals[index];if(!t)return;
  const where=s=>`${e(s.file)} ${s.where?e(s.where):(s.sheet?"· "+e(s.sheet)+" ":"")+"第 "+s.row+" 行"}${s.column?' · '+e(s.column):''}`;
  const body=`<section class="modal-section"><div class="original-text">${e(t.student_id)} · ${e(t.student_name)} · ${e(t.course)} ${e(t.term)}<br>总评：<strong>${t.total??''}</strong> ${outcomeBadge(t.outcome)}</div>${t.notes.length?`<div class="notice amber" style="margin-top:10px">${t.notes.map(e).join('<br>')}</div>`:''}</section>${t.components.map(p=>`<section class="modal-section"><h3>${e(p.name)} · 权重 ${p.weight}% · 得分 ${p.percent??'—'}${p.weighted!=null?` → 计入 ${p.weighted}`:''}${p.overridden?' '+badge('已手动修改','amber'):''}</h3><p class="muted">${e(p.how)}</p><div class="form-actions" data-adjust="${index}" data-component="${e(p.name)}" style="margin:6px 0 10px;justify-content:flex-start;gap:8px"><input type="number" data-adjust-value min="0" max="100" step="0.01" placeholder="改为（百分制）" style="width:140px"><input type="text" data-adjust-note maxlength="200" placeholder="原因（可选）" style="width:200px"><button class="button small" type="button" data-action="adjust">修改</button>${p.overridden?'<button class="button ghost small" type="button" data-action="adjust-reset">恢复计算值</button>':''}</div>${p.records.map(r=>`<details class="review-card"><summary>${e(r.assessment)}${r.occurrence?' '+e(r.occurrence):''}：${e(r.shown)} · ${r.sources.length} 处来源</summary>${r.sources.map(s=>`<div style="margin-top:6px"><small>${where(s)}</small> ${locateButton(s,'在原件中查看')}<pre class="code-box">${e(JSON.stringify(s.raw,null,2))}</pre></div>`).join('')}</details>`).join('')||'<p class="muted">没有记录</p>'}</section>`).join('')}<section class="modal-section"><h3>规则</h3><ul class="rule-list">${(state.task.result.rule_lines||[]).map(x=>`<li>${e(x)}</li>`).join('')}</ul></section>`;
  $('#modal').innerHTML=`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-header"><h2 id="modal-title">总评计算过程</h2><button class="modal-close" data-action="close-modal" aria-label="关闭">×</button></div><div class="modal-body">${body}</div></section>`;
  $('#modal').hidden=false;document.body.style.overflow='hidden';$('.modal-close').focus();
}

function traceView(task) {
  const events=task.events||[];
  if(!events.length) return empty('任务已进入队列','执行后，这里会逐步记录实际调用的工具与处理结果。');
  return `<div class="trace">${events.map(event=>`<div class="trace-event"><span class="trace-point ${event.status==='failed'?'failed':event.status==='running'?'waiting':''}"></span><div class="trace-title"><span>${e(event.title)}</span>${event.status==='running'?'<span class="spinner"></span>':event.status==='failed'?badge('未完成','red'):''}</div><div class="trace-meta"><span>${date(event.created_at)}</span>${badge(modeNames[event.mode]||event.mode,event.mode==='model'?'blue':event.mode==='human'?'amber':'')}<span>${event.elapsed_ms!=null?(event.elapsed_ms/1000).toFixed(2)+' s':''}</span></div><details><summary>查看处理记录</summary><pre class="code-box">${e(JSON.stringify(event.detail,null,2))}</pre></details></div>`).join('')}${task.decisions?.length?`<div style="padding-top:20px;border-top:1px solid var(--line);margin-top:22px"><h3>人工提交历史</h3>${task.decisions.map(d=>`<details style="margin-top:10px"><summary>${date(d.created_at)} · ${d.stage==='mapping'?'指明学生/成绩列':'确认'}</summary><pre class="code-box">${e(JSON.stringify(d.payload,null,2))}</pre></details>`).join('')}</div>`:''}</div>`;
}

function sourceView(task) {
  return `<div class="source-grid">${task.files.map(f=>`<div class="source-card"><div><strong>${e(f.name)}</strong><small>上传的原始文件 · 不被处理结果覆盖</small></div><a class="button small" href="/api/tasks/${task.id}/sources/${f.index}">${icon('download')}下载原始文件</a></div>`).join('')}</div>`;
}

function settingsPage() {
  const m=state.config.model;
  return `<div class="page-heading"><div><div class="eyebrow">MODEL CONNECTION</div><h1>连接你的模型，让语义解析参与工作。</h1><p>支持 DeepSeek、Qwen 及兼容的聊天接口。执行记录会标明实际调用情况。</p></div></div><div class="settings-layout"><section class="card"><div class="card-head"><h2>模型连接</h2>${badge(m.configured?'已配置':'尚未配置',m.configured?'green':'')}</div><div class="card-body"><p class="settings-description">规则流程可以独立运行。接入模型后，可辅助识别陌生表头并提出字段映射建议，新增映射需要确认后采用。</p><div class="provider-options"><button class="provider-option ${state.provider==='deepseek'?'active':''}" data-provider="deepseek">DeepSeek</button><button class="provider-option ${state.provider==='qwen'?'active':''}" data-provider="qwen">Qwen / 百炼</button><button class="provider-option ${state.provider==='custom'?'active':''}" data-provider="custom">其他兼容接口</button></div><form id="model-form"><div class="form-field"><label class="form-label" for="model-base">接口基础地址</label><input id="model-base" type="text" placeholder="https://api.deepseek.com" value="${e(m.base_url||state.config.presets.deepseek.base_url)}" required><div class="form-help">填写服务商控制台提供的基础地址；系统会追加 /chat/completions。Qwen 地址与密钥需属于同一地域，可按控制台地址调整。</div></div><div class="form-field"><label class="form-label" for="model-name">模型名称</label><input id="model-name" type="text" value="${e(m.model||state.config.presets.deepseek.model)}" required><div class="form-help">填写当前账号实际可调用的模型名，预置值可修改。</div></div><div class="form-field"><label class="form-label" for="model-key">API Key <small>${m.key_configured?'已有密钥，留空可保留当前同地址配置':''}</small></label><input id="model-key" type="password" autocomplete="off" placeholder="仅发送到本机服务，保存在当前进程内存"><div class="form-help">密钥不写入任务、导出报告或浏览器存储；服务重启后需重新填写。也可通过 B7_LLM_* 环境变量配置。</div></div><div class="form-actions"><div class="button-row"><button class="button primary" type="submit">保存连接</button><button class="button" type="button" data-action="test-model">保存并测试</button></div><button class="button ghost" type="button" data-action="clear-model">清除连接</button></div><div id="model-feedback" class="settings-status"></div></form></div></section><section class="notice" style="margin-top:18px">模型会接收本次任务必要的表头与少量样例。演示时建议使用合成成绩数据。<br><a class="settings-link" href="https://api-docs.deepseek.com/" target="_blank" rel="noopener">DeepSeek 官方文档 ↗</a>　<a class="settings-link" href="https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope" target="_blank" rel="noopener">Qwen 官方文档 ↗</a></section></div>`;
}

// [key, label, what it measures, true when a lower number is better]
const EVAL_METRICS = {
  '成绩整合与总评': [
    ['ocr_cells','照片 / 扫描件识别','与原件逐格比对的单元格准确率'],
    ['mapping_tables','字段对应','模型建议无需修改即可使用的表格'],
    ['rules_exact','规则理解','组成项、权重、计算方式、状态处理全部与老师本意一致'],
    ['totals_if_rule_confirmed','直接确认规则时的总评','老师不改模型草稿就确认，总评与标准答案一致'],
    ['rules_unsupported_pointed_out','指出规则表做不到的要求','如“酌情加分”，应交给老师而不是编造计算'],
    ['rules_unclear_per_draft','每份草稿的待确认点','条数，越少越聚焦',true],
    ['planted_caught','预设问题发现','同名、录错学号、超满分、名单外学生、分数冲突'],
    ['unexpected_issues_per_run','意外疑点','每次运行中预设之外的提示数',true],
    ['final_records','复核后的记录','整合后每条考核记录与标准答案一致'],
    ['final_totals','复核后的总评','每名学生的总评与标准答案一致'],
  ],
  '工作考核评分': [
    ['scheme_indicators','方案拆解','指标的计分方式、分值、上限、必交材料、评价等级全部正确'],
    ['material_person','材料归属','判断材料属于哪位被考核人'],
    ['material_indicator','指标对应','判断材料支撑哪个指标'],
    ['material_level','级别判断','按方案是否计分、计几分'],
    ['dedupe_pairs','同一项目合并','两份材料是否同一项目的判断'],
    ['flags_caught','预设问题标出','多人申报、校级奖、未署名等'],
    ['flags_extra_per_run','多余提示','每次运行中预设之外被标出的材料数',true],
    ['quotes_found_in_text','摘录原文可查到','模型摘录的原句能在材料文字中逐字找到（图片内容除外）'],
    ['suggestions_agree_clear','建议等级','与参考等级一致（不含有争议的项）'],
    ['computed_items_unreviewed','未经复核的计算项','不做人工确认时程序计算项的正确率，说明复核为何必要'],
    ['appraisal_final_items','复核后的各项得分','每人每项得分与标准答案一致'],
  ],
};
const pct = v => v==null?'—':(v*100).toFixed(v>=0.995&&v<1?1:0)+'%';
function metricValue(m,lower){ if(!m||m.den===0)return '—'; return lower?(+m.value.toFixed(2)).toString():pct(m.value); }
function metricRange(key,report,lower){
  const values=(report.per_repeat||[]).map(r=>r[key]).filter(m=>m&&m.den);
  if(values.length<2)return '';
  const nums=values.map(m=>m.value),lo=Math.min(...nums),hi=Math.max(...nums);
  return lo===hi?'各轮一致':`各轮 ${lower?+lo.toFixed(2):pct(lo)} – ${lower?+hi.toFixed(2):pct(hi)}`;
}
function evalExamples(run){
  const s=run.stages||{},out=[];
  Object.entries(s.ocr||{}).forEach(([f,v])=>v.examples.forEach(x=>out.push(`识别 ${f}：${x}`)));
  (s.mapping?.examples||[]).forEach(x=>out.push('字段：'+x));
  (s.rules?.notes||[]).forEach(x=>out.push('规则：'+x));
  if(s.rules?.unclear_expected&&!s.rules.unclear_found)out.push('规则：没有指出规则表做不到的要求');
  (run.issues?.unexpected_examples||[]).forEach(x=>out.push('意外疑点：'+x));
  (run.records?.examples||[]).forEach(x=>out.push('记录：'+x));
  (run.totals?.examples||[]).forEach(x=>out.push('总评：'+x));
  (s.scheme?.examples||[]).forEach(x=>out.push('方案：'+x));
  (s.materials?.examples||[]).forEach(x=>out.push('材料：'+x));
  (s.materials?.flags_missed_examples||[]).forEach(x=>out.push('未标出：'+x));
  (s.materials?.flags_extra_examples||[]).forEach(x=>out.push('多余提示：'+x));
  (s.suggestions?.details||[]).filter(d=>d.got!==d.want).forEach(d=>out.push(`建议等级 ${d.key}：参考 ${d.want}${d.debatable?'（有争议）':''}，模型 ${d.got||'未给出'}`));
  (run.final_items?.examples||[]).forEach(x=>out.push('得分：'+x));
  if(run.error)out.push('运行错误：'+run.error);
  return out;
}
function evaluationPage(){
  const ev=state.evaluation||{},report=ev.report,configured=state.config.model.configured;
  const progress=ev.running?`<div class="notice blue">评测运行中：${e(ev.progress?.current||'准备中')}（已完成 ${ev.progress?.done||0} / ${ev.progress?.total||'?'}）。页面会自动刷新。</div>`:'';
  const controls=`<section class="card"><div class="card-head"><h2>运行评测</h2>${badge(configured?'将使用 '+state.config.model.model:'需要连接模型',configured?'green':'')}</div><div class="card-body"><p class="settings-description">用当前连接的模型，把下列合成用例完整跑一遍：系统按真实流程处理，复核环节由脚本按标准答案作答（相当于一位认真核对原件的老师），从而分别衡量每个模型环节的准确率。多轮运行可以看出结果是否稳定。</p><div class="form-actions"><label class="form-label" style="margin:0">轮数 <select id="eval-repeat" style="width:auto;display:inline-block;margin-left:6px"><option>1</option><option>2</option><option selected>3</option></select></label><button class="button primary" data-action="run-eval" ${configured&&!ev.running?'':'disabled'}>开始评测 ${icon('arrow')}</button></div></div></section>`;
  const cases=`<section class="card"><div class="card-head"><h2>评测用例</h2><small class="muted">全部为合成数据，标准答案由生成脚本给出</small></div><div class="table-wrap"><table><thead><tr><th>用例</th><th>考察点</th><th>说明</th></tr></thead><tbody>${(ev.cases||[]).map(c=>`<tr><td style="white-space:nowrap"><b>${e(c.id)}</b> ${e(c.title)}</td><td>${badge(c.level)}</td><td style="white-space:normal">${e(c.about)}</td></tr>`).join('')}</tbody></table></div></section>`;
  if(!report) return `<div class="page-heading"><div><div class="eyebrow">EVALUATION</div><h1>效果评测</h1><p>每一步模型处理有多准，用带标准答案的测试集来回答。</p></div></div>${progress}${controls}${cases}`;
  const m=report.metrics,runs=report.runs||[],failed=m.failed_runs?.num||0;
  const groups=Object.entries(EVAL_METRICS).filter(([,list])=>list.some(([k])=>m[k])).map(([title,list])=>`<section class="card"><div class="card-head"><h2>${title}</h2></div><div class="table-wrap"><table><thead><tr><th>环节</th><th>结果</th><th>依据</th><th>稳定性</th><th>衡量什么</th></tr></thead><tbody>${list.filter(([k])=>m[k]).map(([k,label,about,lower])=>`<tr><td style="white-space:nowrap"><b>${label}</b></td><td class="mono" style="font-size:16px;white-space:nowrap">${metricValue(m[k],lower)}</td><td class="mono muted" style="white-space:nowrap">${lower?`共 ${m[k].num} 处 · ${m[k].den} 次运行`:`${m[k].num} / ${m[k].den}`}</td><td class="muted" style="white-space:nowrap">${metricRange(k,report,lower)}</td><td class="muted" style="white-space:normal">${e(about)}</td></tr>`).join('')}</tbody></table></div></section>`).join('');
  const byCase=(report.cases||[]).map(c=>{
    const mine=runs.filter(r=>r.case===c.id),examples=mine.flatMap(r=>evalExamples(r).map(x=>`第${r.repeat}轮 · ${x}`));
    const secs=mine.length?Math.round(mine.reduce((s,r)=>s+(r.seconds||0),0)/mine.length):0;
    const ok=mine.filter(r=>r.status==='completed').length;
    return `<details class="review-card"><summary><b>${e(c.id)}</b> ${e(c.title)}　${badge(`${ok}/${mine.length} 轮完成`,ok===mine.length?'green':'red')} ${badge(examples.length?`${examples.length} 处差异`:'与标准答案一致',examples.length?'amber':'green')} <small class="muted">平均 ${secs} 秒</small></summary>${examples.length?`<ul class="rule-list" style="margin-top:10px">${examples.slice(0,30).map(x=>`<li>${e(x)}</li>`).join('')}</ul>`:'<p class="muted" style="margin-top:8px">各环节结果都与标准答案一致。</p>'}</details>`;
  }).join('');
  const history=(ev.history||[]).length>1?`<div class="filters" style="margin-top:10px">${ev.history.slice(0,6).map(f=>`<button class="filter" data-eval-file="${e(f)}">${e(f.replace('eval_','').replace('.json','').replace('_',' '))}</button>`).join('')}</div>`:'';
  return `<div class="page-heading"><div><div class="eyebrow">EVALUATION</div><h1>效果评测</h1><p>每一步模型处理有多准，用带标准答案的测试集来回答。</p></div>${badge('合成数据评测','amber')}</div>${progress}
  <div class="stats">${stat('评测用例',report.cases.length,`${report.repeat} 轮 · 共 ${runs.length} 次运行`,'list')}${stat('复核后总评正确率',pct(m.final_totals?.value),'成绩整合各用例','check','teal')}${stat('复核后考核得分正确率',pct(m.appraisal_final_items?.value),'工作考核各用例','check','teal')}${stat('运行失败',failed,failed?'见下方用例详情':'全部运行完成','alert',failed?'amber':'')}</div>
  <div class="notice">模型：${e(report.model)} · ${e(date(report.started_at))} 开始，${e(date(report.finished_at))} 结束。以下数字只说明这套合成测试集上的表现，不代表真实材料的准确率；真实效果需要用脱敏的真实材料再测。${history}</div>
  ${groups}<section class="card"><div class="card-head"><h2>逐个用例</h2><small class="muted">展开查看与标准答案不一致的地方</small></div><div class="card-body" style="display:grid;gap:10px">${byCase}</div></section>${controls}${cases}`;
}

function render() {
  renderNav();
  $('#content').innerHTML=state.page==='new'?newPage():state.page==='tasks'?tasksPage():state.page==='evaluation'?evaluationPage():state.page==='settings'?settingsPage():taskPage();
  bindForms();
}

async function refreshTasks() { state.tasks=await api('/api/tasks'); }
async function loadTask(id) { state.task=await api('/api/tasks/'+encodeURIComponent(id)); }
async function route() {
  const value=location.hash.slice(1)||'new';
  state.files=[];
  if(value.startsWith('task/')) {
    state.page='task';state.task=null;state.tab='result';render();
    try { await loadTask(value.slice(5)); } catch(error) { toast(error.message);navigate('tasks');return; }
  } else state.page=Object.keys(labels).includes(value)&&value!=='task'?value:'new';
  if(state.page==='evaluation') { try { state.evaluation=await api('/api/evaluation'); } catch(error) { toast(error.message); } }
  render();
  window.scrollTo(0,0);
}

async function createDemo(kind) {
  if(state.busy) return;
  state.busy=true;
  try { const task=await post('/api/demo/'+kind);await refreshTasks();navigate('task/'+task.id); }
  catch(error){toast(error.message);}finally{state.busy=false;}
}

function bindForms() {
  const form=$('#task-form');
  if(form) {
    $('#file-input').addEventListener('change',event=>{addFiles([...event.target.files].map(f=>({file:f,name:f.name})));event.target.value='';});  // reset so the same file can be picked again after removing it
    $('#folder-input').addEventListener('change',event=>{addFiles([...event.target.files].map(f=>({file:f,name:f.webkitRelativePath||f.name})));event.target.value='';});
    $('#rules-file').addEventListener('change',event=>{const f=event.target.files[0];event.target.value='';if(f)readRulesFile(f);});
    renderFileList();
    const drop=$('#dropzone');
    drop.addEventListener('dragover',event=>{event.preventDefault();drop.classList.add('dragging');});
    drop.addEventListener('dragleave',()=>drop.classList.remove('dragging'));
    drop.addEventListener('drop',async event=>{event.preventDefault();drop.classList.remove('dragging');addFiles(await droppedFiles(event.dataTransfer));});
    const rules=$('#rules-text');
    rules.addEventListener('dragover',event=>event.preventDefault());
    rules.addEventListener('drop',event=>{const f=event.dataTransfer.files[0];if(f){event.preventDefault();readRulesFile(f);}});
    form.addEventListener('submit',async event=>{
      event.preventDefault();const button=$('#create-submit');
      if(!state.files.length){toast('请先添加材料。');return;}
      button.disabled=true;button.innerHTML='<span class="spinner"></span> 正在上传…';
      const data=new FormData(form);
      state.files.forEach(f=>data.append('files',f.file,f.name));
      try{const task=await api('/api/tasks',{method:'POST',body:data});await refreshTasks();navigate('task/'+task.id);}catch(error){toast(error.message);button.disabled=false;button.innerHTML=`开始处理 ${icon('arrow')}`;}
    });
  }
  const kindSelect=$('#task-kind');
  if(kindSelect)kindSelect.addEventListener('change',()=>{$('#kind-source').value='';});
  const templateSelect=$('#task-template');
  if(templateSelect)templateSelect.addEventListener('change',()=>{
    const t=(state.config.templates||[]).find(x=>x.id===templateSelect.value);if(!t)return;
    $('#rules-text').value=t.text;$('#task-kind').value=t.kind;$('#kind-source').value='template';
    toast(`已填入模板“${t.name}”的规则。不改动规则，就直接沿用当时确认的理解；改了会重新理解。`);
  });
  const confirmForm=$('#confirm-form');
  if(confirmForm) confirmForm.addEventListener('submit',submitConfirm);
  const add=(input,named)=>input&&input.addEventListener('change',event=>{state.modFiles.push(...[...event.target.files].filter(f=>!HIDDEN_FILE.test(named(f))).map(f=>({file:f,name:named(f)})));event.target.value='';renderModFiles();});
  add($('#mod-file-input'),f=>f.name);add($('#mod-folder-input'),f=>f.webkitRelativePath||f.name);
  renderModFiles();
  const modelForm=$('#model-form');
  if(modelForm) modelForm.addEventListener('submit',event=>{event.preventDefault();saveModel(false);});
  const search=$('#task-search');
  if(search) search.addEventListener('input',()=>{state.search=search.value;$('#task-table-result').innerHTML=taskTable(state.tasks.filter(t=>(state.filter==='all'||t.status===state.filter)&&t.name.toLowerCase().includes(state.search.toLowerCase())));});
}

// Choosing or dropping files adds to the list; each file can be taken out again before the task starts.
// Entries are {file, name}: `name` keeps the folder path ('A班/问答/01.png') so same-named photos in two folders stay apart.
const HIDDEN_FILE=/(^|\/)(\.|__MACOSX|~\$|Thumbs\.db$|desktop\.ini$)/i;
function addFiles(incoming) {
  const {files:limit,upload_mb:mb}=state.config.limits,skipped=[];
  const list=[...state.files];
  for(const f of incoming){
    if(HIDDEN_FILE.test(f.name))continue;
    const max=/\.zip$/i.test(f.name)?200:mb;  // a zip is unpacked on the server and counted by what is inside
    if(f.file.size>max*1024*1024){skipped.push(`${f.name}（超过 ${max}MB）`);continue;}
    const same=list.findIndex(x=>x.name===f.name);
    if(same>=0)list[same]=f; else list.push(f);  // the same name again replaces the earlier copy
  }
  if(list.length>limit){skipped.push(...list.splice(limit).map(f=>`${f.name}（超过 ${limit} 个）`));}
  state.files=list;
  renderFileList();
  if(skipped.length)toast('未加入：'+skipped.join('、'));
}
// A dropped folder arrives as a directory entry; walk it so every file inside is added with its relative path.
async function droppedFiles(transfer) {
  const entries=[...transfer.items||[]].map(item=>item.webkitGetAsEntry&&item.webkitGetAsEntry()).filter(Boolean);
  if(!entries.length)return [...transfer.files].map(f=>({file:f,name:f.name}));
  const out=[];
  const walk=async(entry,prefix)=>{
    if(entry.isFile){out.push({file:await new Promise((ok,fail)=>entry.file(ok,fail)),name:prefix+entry.name});return;}
    const reader=entry.createReader();let batch;
    do{batch=await new Promise((ok,fail)=>reader.readEntries(ok,fail));for(const child of batch)await walk(child,prefix+entry.name+'/');}while(batch.length);
  };
  for(const entry of entries)await walk(entry,'');
  return out;
}
async function readRulesFile(file) {
  const data=new FormData();data.append('file',file,file.name);
  try{const r=await api('/api/rules/extract',{method:'POST',body:data});$('#rules-text').value=r.text;toast(`已读取“${file.name}”${r.truncated?'（过长，只保留前 6000 字）':''}，可以在框里修改`);}
  catch(error){toast(error.message);}
}
function removeFile(index){ state.files.splice(index,1);renderFileList(); }
function renderFileList() {
  const el=$('#file-list');if(!el)return;
  el.innerHTML=state.files.map((f,i)=>`<span class="file-chip">${e(f.name)} · ${f.file.size<1048576?Math.max(1,Math.round(f.file.size/1024))+' KB':(f.file.size/1048576).toFixed(1)+' MB'} <button type="button" class="chip-remove" data-remove-file="${i}" aria-label="移除 ${e(f.name)}" title="移除">×</button></span>`).join('')
    +(state.files.length?` <small class="muted">共 ${state.files.length} 个</small> <button type="button" class="button ghost small" data-action="clear-files">全部清空</button>`:'');
}

function collectConfirm(form) {
  const kind=form.dataset.kind,payload={decisions:{},mappings:{},materials:{},judgements:{}};
  if(kind==='understand') {
    payload.answers=$$('[data-question]',form).map(card=>{const other=$('[data-other]',card).value.trim(),picked=$('input[type=radio]:checked',card);return other||(picked?picked.value:'');});
    payload.note=$('[data-note]',form).value.trim();
    return payload;
  }
  if(kind==='mapping') {
    $$('[data-map-table]',form).forEach(s=>{if(s.value)(payload.mappings[s.dataset.mapTable]??={})[s.dataset.mapField]=s.value;});
    $$('[data-item-table]',form).forEach(b=>{const m=(payload.mappings[b.dataset.itemTable]??={});m.item_columns??=[];if(b.checked)m.item_columns.push(b.value);});
    return payload;
  }
  $$('[data-issue]',form).forEach(card=>{
    const value=$('[data-choice]',card).value;if(!value)return;
    const action=value.startsWith('select:')?'select':value,choice={action};
    if(action==='select')choice.record_id=value.slice(7);
    if(action==='correct'){const pick=$('[data-correct-id]',card),typed=$('[data-correct-id-text]',card);choice.student_id=(pick&&pick.value)||(typed?.value??'');choice.score=$('[data-correct-score]',card)?.value??'';}
    payload.decisions[card.dataset.issue]=choice;
  });
  $$('[data-table]',form).forEach(card=>{
    const original=JSON.parse(card.dataset.mapping),edited={...original};
    $$('[data-field]',card).forEach(s=>{if(s.value)edited[s.dataset.field]=s.value;else delete edited[s.dataset.field];});
    const items=$$('[data-item]',card).filter(b=>b.checked).map(b=>b.value);
    if(items.length)edited.item_columns=items;else delete edited.item_columns;
    if(JSON.stringify(edited)!==JSON.stringify(original))payload.mappings[card.dataset.table]=edited;
  });
  payload.fills=$$('[data-fill]',form).filter(input=>input.value.trim()).map(input=>({...JSON.parse(input.dataset.fill),value:input.value.trim()}));
  $$('[data-material]',form).forEach(row=>{const v=k=>$(`[data-k="${k}"]`,row);payload.materials[row.dataset.material]={person:v('person').value,indicator:v('indicator').value,excluded:v('excluded').checked,note:v('note').value,doc_type:v('doc_type').value,level:v('level').value,project:v('project').value,...(v('accepted')?{accepted:v('accepted').checked}:{})};});
  payload.relations={};$$('[data-relation]',form).forEach(s=>{if(s.value!==s.dataset.was)payload.relations[s.dataset.relation]=s.value;});
  payload.scheme_answers={};$$('[data-scheme-question]',form).forEach(card=>{const picked=$('input[type=radio]:checked',card);if(picked)payload.scheme_answers[card.dataset.schemeQuestion]=picked.value;});
  $$('[data-judge]',form).forEach(row=>{const score=$('[data-k="score"]',row).value;if(score!=='')payload.judgements[row.dataset.judge]={score:Number(score),note:$('[data-k="note"]',row).value};});
  return payload;
}

async function submitConfirm(event) {
  event.preventDefault();const form=event.target,button=$('button[type=submit]',form);button.disabled=true;
  try{await post('/api/tasks/'+state.task.id+'/review',collectConfirm(form));await loadTask(state.task.id);await refreshTasks();render();toast(form.dataset.kind==='understand'?'已收到，开始处理。':'已确认，正在生成结果。');}
  catch(error){toast(error.message);button.disabled=false;}
}

// A teacher can still change one component of one student after the result is out; the program recomputes the total.
async function adjustComponent(button) {
  const box=button.closest('[data-adjust]'),index=Number(box.dataset.adjust),t=state.task.result.totals[index];
  const reset=button.dataset.action==='adjust-reset',raw=$('[data-adjust-value]',box).value;
  if(!reset&&raw===''){$('[data-adjust-value]',box).focus();return;}
  button.disabled=true;
  try{
    const r=await post('/api/tasks/'+state.task.id+'/adjust',{student_id:t.student_id,component:box.dataset.component,value:reset?null:Number(raw),note:$('[data-adjust-note]',box).value});
    Object.assign(state.task.result,r);render();openTotal(index);toast(reset?'已恢复为计算值。':'已修改并重新计算，导出文件也已更新。');
  }catch(error){toast(error.message);button.disabled=false;}
}

async function revise(button) {
  const input=$('#revise-text'),text=input.value.trim();
  if(!text){input.focus();return;}
  button.disabled=true;button.innerHTML='<span class="spinner"></span> 正在修改';
  try{
    const pending=await post('/api/tasks/'+state.task.id+'/revise',{text});
    state.task.result.pending=pending;
    if(state.task.kind==='appraisal'&&pending.scheme_changed){render();toast('指标已修改。');return;}
    $('#rule-section').innerHTML=state.task.kind==='appraisal'?schemeSection(pending):ruleSection(pending);
    const preview=$('#preview-section');if(preview)preview.innerHTML=previewSection(pending);
    toast(pending.errors?.length?'已修改，但还有问题需要处理。':'已按你的话修改，请看下面的结果。');
  }catch(error){toast(error.message);button.disabled=false;button.textContent='修改';}
}

async function reparse(button) {
  button.disabled=true;button.innerHTML='<span class="spinner"></span> 正在重新理解';
  try{state.task.result.pending=await post('/api/tasks/'+state.task.id+'/reparse',{});render();toast('已重新理解规则，请核对。');}
  catch(error){toast(error.message);button.disabled=false;button.textContent='重新理解规则';}
}

async function saveModel(test) {
  const feedback=$('#model-feedback');feedback.textContent=test?'正在保存并进行实际连接测试…':'正在保存…';
  const buttons=$$('button',$('#model-form'));buttons.forEach(b=>b.disabled=true);
  try {
    state.config.model=await post('/api/settings/model',{base_url:$('#model-base').value,model:$('#model-name').value,api_key:$('#model-key').value});
    $('#model-key').value='';renderNav();
    if(test){await post('/api/settings/model/test');feedback.textContent='连接测试通过，模型返回了有效的结构化结果。';}
    else feedback.textContent='连接配置已保存到本机服务内存。尚未进行实际调用测试。';
    feedback.style.color='var(--teal)';
  }catch(error){feedback.textContent=error.message;feedback.style.color='var(--red)';}
  finally{buttons.forEach(b=>b.disabled=false);}
}

const sourceLink=(task,m,label)=>`<a class="settings-link" href="/api/tasks/${task.id}/sources/${m.index}?inline=1" target="_blank" rel="noopener">${label||e(m.file)}</a>`;
const quoteList=quotes=>(quotes||[]).map(q=>`<div class="quote-line"><small>“${e(q.text)}”${q.verified===true?' '+badge('原文核对一致','green'):q.verified===false?' '+badge('原文中未找到','red'):q.verified===null?' '+badge('来自图片，无法逐字比对'):''}</small></div>`).join('');

function appraisalResult(t) {
  const r=t.result;
  if(!r.results) return empty('结果正在形成',t.status==='waiting_review'?'请在“评分人确认”中完成当前步骤。':'处理过程中可在“执行记录”查看当前步骤。');
  const inds=r.scheme.indicators;
  return `<div class="result-intro"><span>按项计分与材料齐全度由程序计算；评价类指标为评分人评定。</span><span>${r.results.length} 人</span></div><div class="table-wrap"><table><thead><tr><th>被考核人</th><th>总分</th><th></th>${inds.map(i=>`<th>${e(i.name)}<br><small class="muted">${i.max}</small></th>`).join('')}</tr></thead><tbody>${r.results.map((p,n)=>`<tr><td>${e(p.person)}</td><td><strong>${p.total??'—'}</strong></td><td><button class="button ghost small" data-person-row="${n}">评分依据 ↗</button></td>${p.items.map(i=>`<td>${i.score??'—'}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function openPerson(index) {
  const t=state.task,r=t.result.results[index];if(!r)return;
  const mats=t.result.materials;
  const body=r.items.map(i=>`<section class="modal-section"><h3>${e(i.group)} / ${e(i.name)} · ${i.score??'—'} / ${i.max} 分</h3><p class="muted">${e(state.config.methods[i.method])}：${e(i.how)}</p>${i.events?.length?`<ul class="rule-list">${i.events.map(ev=>`<li>${e(ev.label)}${ev.level?' · '+e(ev.level):''}：${ev.points==null?'不计分':ev.points+' 分'}${ev.materials.length>1?`（${ev.materials.length} 份材料合并）`:''}</li>`).join('')}</ul>`:''}${i.suggestion?`<div class="notice" style="margin-top:8px">模型建议：${e(i.suggestion.level||'无')}${i.suggestion.score!=null?`（${i.suggestion.score} 分）`:''}；评分人最终：${i.score} 分</div>`:''}${[...i.materials,...(i.left_out||[])].map(id=>mats.find(m=>m.id===id)).filter(Boolean).map(m=>`<details class="review-card"><summary>${MATERIAL_STATES[m.status]?badge(...MATERIAL_STATES[m.status])+' ':''}${e(m.file)} · ${e(m.doc_type)}</summary>${(m.reasons||[]).map(x=>`<div><small>${e(x)}</small></div>`).join('')}<p>${e(m.summary)}</p>${quoteList(m.quotes)}<p>${sourceLink(t,m,'打开原件 ↗')}</p></details>`).join('')}</section>`).join('');
  $('#modal').innerHTML=`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-header"><h2 id="modal-title">${e(r.person)} · 总分 ${r.total??'—'}</h2><button class="modal-close" data-action="close-modal" aria-label="关闭">×</button></div><div class="modal-body">${body}</div></section>`;
  $('#modal').hidden=false;document.body.style.overflow='hidden';$('.modal-close').focus();
}

function openEvidence(index) {
  const task=state.task,row=task.result.rows[index];if(!row)return;
  const body=`<section class="modal-section"><h3>归并后的记录</h3><div class="original-text">${e(row.student_id)} · ${e(row.student_name)} · ${e(row.course_name)}<br>${e(row.term)} / ${e(row.assessment)}${row.occurrence?' / '+e(row.occurrence):''} / ${e(row.attempt)}　${cellScore(row)}${row.matched_by?'<br><small>原记录只有姓名，按课程名单唯一匹配到该学号</small>':''}</div></section><section class="modal-section"><h3>原始来源 · ${row.sources.length} 处</h3>${row.sources.map(s=>`<details class="review-card"><summary>${e(s.file)} · ${s.where?e(s.where):(s.sheet?e(s.sheet)+' · ':'')+'第 '+s.row+' 行'}${s.column?' · '+e(s.column):''}${s.origin==='image'?' · 照片识别':''}</summary>${locateButton(s,'在原件中查看')}<pre class="code-box">${e(JSON.stringify(s.raw,null,2))}</pre></details>`).join('')}</section>${row.reviewed?`<div class="notice">此记录经过人工选择。备注：${e(row.review_note||'未填写')}</div>`:''}`;
  $('#modal').innerHTML=`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-header"><h2 id="modal-title">记录来源与处理依据</h2><button class="modal-close" data-action="close-modal" aria-label="关闭">×</button></div><div class="modal-body">${body}</div></section>`;
  $('#modal').hidden=false;document.body.style.overflow='hidden';$('.modal-close').focus();
}
function closeModal(){ $('#modal').hidden=true;$('#modal').innerHTML='';document.body.style.overflow=''; }

const locateButton=(s,label)=>s.origin==='teacher'?'<small class="muted">老师补录</small>':`<button class="button ghost small" type="button" data-locate='${e(JSON.stringify({file:s.file,sheet:s.sheet||'',row:s.row||0,where:s.where||''}))}'>${e(label||('原件：'+s.file+(s.where?' '+s.where:s.row?' 第'+s.row+'行':'')))} ↗</button>`;
// The record in the file it came from: the rows around it, the PDF page, or the photo with the row that was read from it.
async function openLocate(source) {
  const found=await api(`/api/tasks/${state.task.id}/locate?`+new URLSearchParams(source));
  const base=`/api/tasks/${state.task.id}/`;
  let body;
  if(found.kind==='table') body=`<p class="muted">${e(found.file)}${found.sheet?' · '+e(found.sheet):''}，第 ${found.row} 行（高亮）及前后几行，按原文件显示：</p><div class="table-wrap"><table><thead><tr><th>行</th>${found.headers.map(h=>`<th>${e(h)}</th>`).join('')}</tr></thead><tbody>${found.rows.map(r=>`<tr${r.row_number===found.row?' style="background:var(--amber-soft)"':''}><td class="mono">${r.row_number}</td>${r.values.map(v=>`<td>${e(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p><a class="settings-link" href="${base+found.url}">下载原始文件</a></p>`;
  else if(found.kind==='image') body=`<p class="muted">${e(found.file)}${found.where?'，'+e(found.where):''}。照片里的具体位置无法自动标出，请按条目顺序对照。</p><img src="${base+found.url}" alt="${e(found.file)}" style="max-width:100%;border:1px solid var(--line);border-radius:8px">`;
  else if(found.kind==='pdf') body=`<p class="muted">${e(found.file)}${found.page?`，第 ${found.page} 页`:''}${found.where?'（'+e(found.where)+'）':''}。</p><iframe src="${base+found.url}" title="${e(found.file)}" style="width:100%;height:68vh;border:1px solid var(--line);border-radius:8px"></iframe><p><a class="settings-link" href="${base+found.url}" target="_blank" rel="noopener">在新窗口打开</a></p>`;
  else body=`<p>${e(found.error||'这种文件不能在页面里显示。')}</p><p><a class="settings-link" href="${base+found.url}">下载原始文件</a></p>`;
  $('#modal').innerHTML=`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-header"><h2 id="modal-title">原件中的位置</h2><button class="modal-close" data-action="close-modal" aria-label="关闭">×</button></div><div class="modal-body"><section class="modal-section">${body}</section></div></section>`;
  $('#modal').hidden=false;document.body.style.overflow='hidden';$('.modal-close').focus();
}

function renderModFiles() {
  const el=$('#mod-file-list');if(!el)return;
  el.innerHTML=state.modFiles.map((f,i)=>`<span class="file-chip">${e(f.name)} <button type="button" class="chip-remove" data-remove-mod="${i}" aria-label="移除 ${e(f.name)}">×</button></span>`).join('');
}
async function sendModify(extra={}) {
  const data=new FormData(),t=state.task;
  state.modFiles.forEach(f=>data.append('files',f.file,f.name));
  data.append('remove',JSON.stringify($$('[data-remove-index]').filter(b=>b.checked).map(b=>Number(b.dataset.removeIndex))));
  const rules=$('#mod-rules');
  if(rules&&rules.value!==(t.rules_now??''))data.append('rules_text',rules.value);
  for(const [k,v] of Object.entries(extra))data.append(k,typeof v==='string'?v:JSON.stringify(v));
  await api(`/api/tasks/${t.id}/modify`,{method:'POST',body:data});
  state.modFiles=[];await loadTask(t.id);await refreshTasks();render();toast('已按修改重新处理；没变的材料不会重新识别。');
}

document.addEventListener('click',async event=>{
  const target=event.target.closest('button,a,tr[data-task]');if(!target)return;
  try {
    if(target.dataset.removeFile!=null){event.preventDefault();removeFile(Number(target.dataset.removeFile));}
    else if(target.dataset.action==='clear-files'){event.preventDefault();state.files=[];renderFileList();}
    else if(target.dataset.action==='pick-folder'){event.preventDefault();$('#folder-input').click();}
    else if(target.dataset.action==='pick-rules'){event.preventDefault();$('#rules-file').click();}
    else if(target.dataset.demo){event.preventDefault();await createDemo(target.dataset.demo);}
    else if(target.dataset.task)navigate('task/'+target.dataset.task);
    else if(target.dataset.filter){state.filter=target.dataset.filter;render();}
    else if(target.dataset.tab){state.tab=target.dataset.tab;render();}
    else if(target.dataset.evidenceRow!=null)openEvidence(Number(target.dataset.evidenceRow));
    else if(target.dataset.totalRow!=null)openTotal(Number(target.dataset.totalRow));
    else if(target.dataset.personRow!=null)openPerson(Number(target.dataset.personRow));
    else if(target.dataset.view){state.resultView=target.dataset.view;render();}
    else if(target.dataset.provider){state.provider=target.dataset.provider;$$('[data-provider]').forEach(b=>b.classList.toggle('active',b===target));const preset=state.config.presets[state.provider];if(preset){$('#model-base').value=preset.base_url;$('#model-name').value=preset.model;}}
    else if(target.dataset.action==='close-modal')closeModal();
    else if(target.dataset.action==='revise')await revise(target);
    else if(target.dataset.action==='reparse')await reparse(target);
    else if(target.dataset.action==='adjust'||target.dataset.action==='adjust-reset')await adjustComponent(target);
    else if(target.dataset.action==='switch'){if(!confirm(`改为按“${state.task.kind==='grades'?'工作考核评分':'课程成绩总评'}”重新处理这些材料吗？`))return;const created=await post('/api/tasks/'+state.task.id+'/switch');await refreshTasks();navigate('task/'+created.id);}
    else if(target.dataset.action==='test-model')await saveModel(true);
    else if(target.dataset.action==='clear-model'){state.config.model=await api('/api/settings/model',{method:'DELETE'});render();toast('模型连接已清除。');}
    else if(target.dataset.action==='retry'){await post('/api/tasks/'+state.task.id+'/retry');await loadTask(state.task.id);render();}
    else if(target.dataset.action==='stop'){target.disabled=true;await post('/api/tasks/'+state.task.id+'/stop');await loadTask(state.task.id);render();toast('当前这一步完成后会停下，已完成的步骤会保留。');}
    else if(target.dataset.action==='modify'){target.disabled=true;try{await sendModify();}finally{target.disabled=false;}}
    else if(target.dataset.action==='reopen'){target.disabled=true;try{await sendModify({reopen:'1'});}finally{target.disabled=false;}}
    else if(target.dataset.revoke){if(!confirm('撤回这项处理？会生成新的一版，这个问题会重新列出来让你决定。'))return;target.disabled=true;try{await sendModify({revoke:[target.dataset.revoke]});}finally{target.disabled=false;}}
    else if(target.dataset.action==='undo'){if(!confirm(`撤回第 ${state.task.version} 版的修改，回到第 ${state.task.version-1} 版？`))return;await post('/api/tasks/'+state.task.id+'/undo');await loadTask(state.task.id);await refreshTasks();render();toast('已回到上一版。');}
    else if(target.dataset.removeMod!=null){state.modFiles.splice(Number(target.dataset.removeMod),1);renderModFiles();}
    else if(target.dataset.locate){await openLocate(JSON.parse(target.dataset.locate));}
    else if(target.dataset.action==='save-prefs'){state.config.prefs=await post('/api/prefs',{identity:$('#pref-identity').value,flow:$('#pref-flow').value});render();toast('已保存。新建任务时会预选常用流程。');}
    else if(target.dataset.deleteTemplate){if(!confirm('删除这个规则模板？已有任务不受影响。'))return;await api('/api/templates/'+target.dataset.deleteTemplate,{method:'DELETE'});state.config=await api('/api/config');render();}
    else if(target.dataset.action==='save-template'){const name=prompt('模板名称（如“数据结构总评规则”）：',state.task.name);if(!name)return;await post(`/api/tasks/${state.task.id}/template`,{name});state.config=await api('/api/config');toast('已保存为规则模板，新建任务时可以选用。');}
    else if(target.dataset.useSuggestion!=null){const input=$('[data-k="score"]',target.closest('[data-judge]'));input.value=target.dataset.useSuggestion;input.focus();}
    else if(target.dataset.action==='run-eval'){
      const repeat=Number($('#eval-repeat').value||1);
      if(!confirm(`将用当前模型运行全部 ${state.evaluation.cases.length} 个评测用例 × ${repeat} 轮，约需 ${Math.round(5*repeat)} 分钟，并产生相应的模型调用费用。继续吗？`))return;
      await post('/api/evaluation/run',{repeat});state.evaluation=await api('/api/evaluation');render();toast('评测已开始，可以离开此页，完成后回来查看。');
    }
    else if(target.dataset.evalFile){state.evaluation=await api('/api/evaluation?file='+encodeURIComponent(target.dataset.evalFile));render();}
  }catch(error){toast(error.message);}
});
document.addEventListener('change',async event=>{
  if(event.target.matches('[data-digits]')){try{const pending=await post('/api/tasks/'+state.task.id+'/rounding',{digits:Number(event.target.value)});state.task.result.pending=pending;$('#rule-section').innerHTML=ruleSection(pending);$('#preview-section').innerHTML=previewSection(pending);toast('已改为保留 '+event.target.value+' 位小数。');}catch(error){toast(error.message);}}
  if(event.target.matches('[data-choice]')){const card=event.target.closest('[data-issue]'),edit=$('.row-correction',card);if(edit){edit.hidden=event.target.value!=='correct';edit.style.display=event.target.value==='correct'?'flex':'none';}}
  if(event.target.matches('[data-correct-id]')){const typed=$('[data-correct-id-text]',event.target.closest('[data-issue]'));if(typed)typed.hidden=event.target.value!=='';}
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeModal();if(event.key==='Enter'&&event.target.matches('#revise-text')){event.preventDefault();$('[data-action="revise"]').click();}if(event.key==='Enter'&&event.target.matches('tr[data-task]'))navigate('task/'+event.target.dataset.task);});
$('#modal').addEventListener('click',event=>{if(event.target===$('#modal'))closeModal();});
window.addEventListener('hashchange',route);

async function start(){
  try{state.config=await api('/api/config');await refreshTasks();await route();}
  catch(error){$('#content').innerHTML=`<div class="notice red">工作台连接失败：${e(error.message)}。请确认本地服务正在运行，再刷新页面。</div>`;}
}
let polling=false;
setInterval(async()=>{
  const busy=state.page==='task'&&state.task&&['queued','running'].includes(state.task.status);
  if(polling||!(busy||state.tasks.some(t=>['queued','running'].includes(t.status))))return;
  polling=true;
  try{
    await refreshTasks();
    if(busy){await loadTask(state.task.id);render();}
    else if(state.page==='tasks')render();  // never re-render the upload form under the user's hands
    else renderNav();
  }catch{}finally{polling=false;}
},1800);
setInterval(async()=>{
  if(state.page!=='evaluation'||!state.evaluation?.running)return;
  try{state.evaluation=await api('/api/evaluation');render();}catch{}
},5000);
start();
