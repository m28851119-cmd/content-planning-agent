const $ = (id) => document.getElementById(id);
const labels = {search_materials:"检索素材",generate_script:"生成脚本",estimate_cost:"核算方案",save_plan:"保存方案",finish:"结束任务",resume:"恢复任务",limit:"达到调用上限",invalid_action:"动作校验",input_validation:"输入检查",model_error:"模型请求失败",web_error:"运行异常",ask_user:"需要补充输入"};
const statuses = {pending:"等待执行",running:"执行中",succeeded:"已完成",failed:"失败",skipped:"已复用",completed:"已完成",incomplete:"未完成",needs_input:"待补充"};
const tones = {succeeded:"success",completed:"success",running:"running",failed:"error",incomplete:"warning",needs_input:"warning",pending:"neutral",skipped:"neutral"};
let current = null, selection = 0, timer = null, history = [], config = {};
const escape = (v) => String(v ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = (v) => v == null ? "—" : Number(v).toLocaleString("zh-CN",{maximumFractionDigits:2});
const badge = (status) => '<span class="badge '+(tones[status]||"neutral")+'">'+escape(statuses[status]||status)+'</span>';
async function api(path,body){
  const response=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||"连接失败，请检查本地服务。");
  return result;
}
function notify(message){$("notice").textContent=message;$("notice").hidden=!message;}
function empty(title,description){
  return '<div class="empty"><div class="empty-visual" aria-hidden="true"><span><svg viewBox="0 0 24 24"><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></svg></span><i></i><span><svg viewBox="0 0 24 24"><path d="M5 4h14v16H5zM9 8h6M9 12h6M9 16h3"/></svg></span><i></i><span><svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg></span></div><h3>'+escape(title)+'</h3><p>'+escape(description)+'</p></div>';
}
function setTab(tab){
  document.querySelectorAll("[data-tab]").forEach(b=>{
    const selected=b.dataset.tab===tab;b.setAttribute("aria-selected",selected);b.tabIndex=selected?0:-1;
    $("view-"+b.dataset.tab).hidden=!selected;
  });
}
document.querySelectorAll("[data-tab]").forEach(b=>{
  b.addEventListener("click",()=>setTab(b.dataset.tab));
  b.addEventListener("keydown",e=>{
    if(!["ArrowLeft","ArrowRight","Home","End"].includes(e.key))return;
    e.preventDefault();const tabs=[...document.querySelectorAll("[data-tab]")];
    let index=tabs.indexOf(b);
    index=e.key==="Home"?0:e.key==="End"?tabs.length-1:(index+(e.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length;
    setTab(tabs[index].dataset.tab);tabs[index].focus();
  });
});
function stepSummary(step){
  if(step.error){
    if(step.error==="injected_failure")return "按设置注入了一次故障，错误已返回模型。";
    if(step.error.includes("save_guardrail_rejected"))return "预算或时间超限，代码护栏已拒绝保存。";
    return step.error;
  }
  const r=step.result||{};
  if(step.status==="skipped")return "复用已成功步骤 "+step.reused_step+"，没有再次调用工具。";
  if(step.status==="running")return "工具正在执行，等待实际返回结果。";
  if(step.tool==="search_materials")return "找到 "+(r.material_ids||[]).length+" 份合成素材";
  if(step.tool==="generate_script")return (r.variant==="lite"?"轻量":"完整")+"脚本已生成，素材 "+(r.material_ids||[]).join("、");
  if(step.tool==="estimate_cost")return "报价 "+num(r.estimate?.total_cost)+" 单位，模拟耗时 "+num(r.estimate?.total_minutes)+" 分钟";
  if(step.tool==="save_plan")return r.already_exists?"方案已存在，返回同一份保存文件。":"方案已保存，费用已记入台账。";
  return statuses[step.status]||step.status;
}
function renderFlow(s){
  if(!s?.plan?.length){
    $("flow-content").innerHTML=s?.active?'<p class="empty-loading">正在等待模型选择第一个动作…</p>':empty(s?.status==="needs_input"?"请先补齐任务信息":s?.reason==="no_feasible_plan"?"暂时没有可行方案":"准备好开始规划了吗？",s?.reason==="no_feasible_plan"?"提高预算或延长时限后，再发起一次任务。":"填写左侧主题、预算与时限，开始一次可追溯的内容规划。");
    return;
  }
  const opened=new Set([...document.querySelectorAll("#flow-content details[open]")].map(d=>d.dataset.step));
  $("flow-content").innerHTML=s.plan.map((step,index)=>{
    const event=[...s.events].reverse().find(e=>e.observation?.step_id===step.id);
    const rationale=event?.rationale;
    return '<article class="flow-item '+escape(step.status)+'"><span class="step-marker">'+(step.status==="succeeded"?"✓":step.status==="failed"?"!":index+1)+'</span><div class="step-head"><strong>'+escape(labels[step.tool]||step.tool)+'</strong><span class="step-id">'+escape(step.id)+(step.args?.variant?' / '+escape(step.args.variant):"")+'</span>'+badge(step.status)+'</div><p class="step-description '+(step.error?"error":"")+'">'+escape(stepSummary(step))+'</p>'+(rationale?'<p class="step-description">'+escape(rationale)+'</p>':"")+(step.dependencies?.length?'<span class="step-result">依赖 '+escape(step.dependencies.join("、"))+'</span>':"")+'<details class="step-detail" data-step="'+escape(step.id)+'" '+(opened.has(step.id)?"open":"")+'><summary>参数与工具结果</summary><pre>'+escape(JSON.stringify({args:step.tool_args||step.args,result:step.result,error:step.error},null,2))+'</pre></details></article>';
  }).join("")+(s.active?'<p class="empty-loading">等待下一次模型决策…</p>':"");
}
function renderPlan(s){
  if(!s?.selected_plan){
    $("plan-content").innerHTML=empty("方案将在估算后呈现","素材、脚本版本和预算经过核算后，会汇总在这里。");
    return;
  }
  const plan=s.selected_plan;
  $("plan-content").innerHTML='<h2>'+escape(plan.topic)+'</h2><div class="plan-script">'+escape(plan.script)+'</div><div class="plan-meta">'+Object.entries(plan.variants).map(([k,v])=>'<span>'+escape(labels[k])+' '+escape(v)+'</span>').join("")+'</div><p class="plan-note">使用素材：'+escape(plan.material_ids.join("、"))+'</p>'+(s.saved?'<p class="plan-note">保存文件：'+escape(s.saved.path)+'</p>':'<p class="plan-note">当前为候选方案，尚未保存。</p>');
}
function renderTrace(s){
  const opened=new Set([...document.querySelectorAll("#trace-content details[open]")].map(d=>d.dataset.event));
  $("trace-content").innerHTML=s?.events?.length?s.events.map((e,index)=>'<details class="trace-event" data-event="'+index+'" '+(opened.has(String(index))?"open":"")+'><summary>第 '+e.step+' 轮 / '+escape(labels[e.action]||e.action)+' / '+escape(e.action)+'</summary><p>'+escape(e.rationale)+'</p><pre>'+escape(JSON.stringify(e,null,2))+'</pre></details>').join(""):'<p class="quiet">尚无运行记录。每轮动作、参数和观察结果将保留在这里。</p>';
}
function renderChart(s){
  const estimates=(s?.plan||[]).filter(p=>p.tool==="estimate_cost"&&p.status==="succeeded").map(p=>p.result.estimate.total_cost);
  if(!estimates.length){$("quote-chart").innerHTML='<p class="quiet">完成首次估算后显示</p>';return;}
  const budget=s.request.budget, max=Math.max(...estimates,budget||0,1)*1.25;
  const width=230, base=88, span=width/estimates.length, bar=Math.min(36,span*.55);
  let markup='<svg viewBox="0 0 250 120" role="img" aria-label="每次估算报价：'+escape(estimates.join("、"))+'；预算 '+escape(budget)+'">';
  estimates.forEach((cost,i)=>{const h=cost/max*70,x=10+span*i+(span-bar)/2;markup+='<rect class="'+(cost>budget?"over-budget":"bar")+'" x="'+x+'" y="'+(base-h)+'" width="'+bar+'" height="'+h+'" rx="3"/><text class="bar-value" x="'+(x+bar/2)+'" y="'+(base-h-6)+'" text-anchor="middle">'+cost+'</text><text x="'+(x+bar/2)+'" y="108" text-anchor="middle">估算 '+(i+1)+'</text>';});
  if(budget!==null){const y=base-budget/max*70;markup+='<line class="budget-line" x1="8" x2="240" y1="'+y+'" y2="'+y+'"/><text x="240" y="'+Math.max(9,y-5)+'" text-anchor="end">预算 '+budget+'</text>';}
  $("quote-chart").innerHTML=markup+"</svg>";
}
function banner(s){
  const element=$("result-banner");element.className="result-banner";element.hidden=true;
  if(!s)return;
  let message="";
  if(s.archived)message="历史运行记录：以下内容来自实际保存的证据，当前没有发起工具或模型调用。";
  else if(s.status==="completed")message=s.saved?.already_exists?"已找到同一份方案，无需重复保存。":"方案已完成并保存，费用与时限均通过代码护栏校验。";
  else if(s.status==="needs_input")message="需要补充："+s.missing_fields.map(k=>({budget:"预算",deadline:"截止时限",topic:"活动主题"}[k]||k)).join("、")+"。填写后重新开始规划。";
  else if(s.reason==="no_feasible_plan")message="没有可行方案。最低成本 "+num(s.gap.minimum_cost)+"，预算缺口 "+num(s.gap.cost)+"；时间缺口 "+num(s.gap.minutes)+" 分钟。";
  else if(s.reason==="max_steps_reached")message="已达到本次累计调用上限，成功结果已保留。点击「继续执行」增加配额并续跑。";
  else if(!s.active&&["pending","running"].includes(s.status))message="服务已中断，已有结果已保留。可以继续执行剩余步骤。";
  else if(s.reason)message="任务未完成（"+s.reason+"）。请检查运行配置；成功结果已保留。";
  if(message){element.textContent=message;element.hidden=false;if(s.status!=="completed"&&!s.archived)element.classList.add("warning");}
}
function render(s){
  current=s;
  $("run-label").textContent=s?(s.archived?"历史运行 / ":s.backend==="mock"?"离线 Mock / ":"真实模型 / ")+s.run_id.slice(0,8):"准备就绪";
  $("run-title").textContent=s?.request.topic||"你的下一份内容计划";
  const status=s?.active&&s.status==="pending"?"running":s?.status;
  $("status").className="badge "+(tones[status]||"neutral");$("status").textContent=statuses[status]||"等待开始";
  const quoted=Boolean(s?.selected_plan),budget=s?s.request.budget:Number($("budget").value),deadline=s?s.request.deadline:Number($("deadline").value);
  $("cost").textContent=quoted?num(s.total_cost):"—";$("minutes").textContent=quoted?num(s.total_minutes):"—";$("charged").textContent=s?num(s.charged_cost):"—";
  $("budget-limit").textContent=" / "+num(budget);$("deadline-limit").textContent=" / "+num(deadline)+" 分钟";
  for(const [id,val,max]of[["cost-meter",s?.total_cost||0,budget],["time-meter",s?.total_minutes||0,deadline]]){
    $(id).max=Math.max(max||0,val,1);$(id).value=val;$(id).classList.toggle("over",max!=null&&val>max);
  }
  $("charge-note").textContent=s?.saved?.already_exists?"幂等保存，不重复扣费":"保存成功后计入台账";
  $("step-count").textContent=s?.plan.length||0;
  $("run-meta").textContent=s?"决策 "+s.used_steps+" / "+s.max_steps+" 轮，工具 "+s.tool_calls+" / "+s.max_tool_calls+" 次":"每一步都有记录，每次调整都有依据。";
  $("run-button").disabled=Boolean(s?.active);$("run-button").querySelector("span").textContent=s?.active?"正在规划…":"开始规划";
  $("run-button").querySelector("svg").classList.toggle("busy-icon",Boolean(s?.active));
  $("download-button").disabled=!s;$("download-trace").disabled=!s?.events?.length;
  $("resume-button").hidden=!s||s.archived||s.active||["completed","needs_input"].includes(s.status);
  renderFlow(s);renderPlan(s);renderTrace(s);renderChart(s);banner(s);
  for(const li of document.querySelectorAll("#route li")){
    const step=[...(s?.plan||[])].reverse().find(p=>p.tool===li.dataset.tool);
    li.className=step?.status==="succeeded"?"done":step?.status||"";
    li.querySelector(".route-status").textContent=step?(statuses[step.status]||step.status):"待执行";
  }
  const decision=[...(s?.events||[])].reverse().find(e=>e.rationale);
  $("latest-decision").textContent=decision?.rationale||"启动任务后，这里会显示模型返回的简要决策依据。";
  $("decision-source").textContent=s?(s.backend==="real"?"来自真实模型返回":"来自 Mock 脚本策略"):"不展示模型内部思维过程";
}
async function refreshHistory(){history=await api("/api/runs");$("history-count").textContent=history.length;}
async function openRun(id,archived=false){
  const token=++selection;clearTimeout(timer);notify("");
  async function poll(){
    try{
      const state=await api((archived?"/api/examples/":"/api/runs/")+encodeURIComponent(id));
      if(token!==selection)return;
      render(state);
      if(state.active)timer=setTimeout(poll,600);else await refreshHistory();
    }catch(error){if(token===selection)notify(error.message+" 可从运行记录重新打开任务。");}
  }
  await poll();
}
$("run-form").addEventListener("submit",async event=>{
  event.preventDefault();notify("");$("run-button").disabled=true;
  const numeric=id=>$(id).value.trim()===""?null:Number($(id).value);
  try{
    const result=await api("/api/runs",{topic:$("topic").value.trim(),budget:numeric("budget"),deadline:numeric("deadline"),backend:$("backend").value,max_steps:numeric("max-steps"),max_tool_calls:numeric("max-calls"),failure:$("failure").value});
    setTab("flow");await openRun(result.run_id);
    if(matchMedia("(max-width:760px)").matches)document.querySelector(".monitor").scrollIntoView({behavior:"instant",block:"start"});
  }catch(error){notify(error.message);$("run-button").disabled=false;}
});
$("resume-button").addEventListener("click",async()=>{
  if(!current||current.archived)return;
  $("resume-button").disabled=true;
  try{await api("/api/runs/"+current.run_id+"/resume",{});setTab("flow");await openRun(current.run_id);}
  catch(error){notify(error.message);}finally{$("resume-button").disabled=false;}
});
document.querySelectorAll("[data-preset]").forEach(b=>b.addEventListener("click",()=>{
  $("topic").value="秋季新品推广";$("budget").value=b.dataset.preset==="failure"?"20":"10";$("deadline").value="120";
  $("backend").value="mock";$("max-steps").value=b.dataset.preset==="resume"?"2":"12";$("max-calls").value="12";
  $("failure").value=b.dataset.preset==="budget"?"":"generate_script";updateMode();
  if(b.dataset.preset!=="budget")document.querySelector(".advanced").open=true;
  notify("已填入「"+b.querySelector("span").textContent+"」参数，点击「开始规划」执行。");
}));
function updateMode(){
  $("mode-help").textContent=$("backend").value==="mock"?"脚本化策略验证流程，不代表真实模型决策能力。":"调用服务端已配置的 "+(config.model||"DeepSeek Pro")+"。密钥不会发送到浏览器。";
}
$("backend").addEventListener("change",updateMode);
async function showLibrary(examples){
  $("library-title").textContent=examples?"实际运行样例":"运行记录";
  $("library-description").textContent=examples?"查看仓库中保留的真实执行证据，包含 Mock 与真实模型。":"本地持久化任务，点击查看结果或继续未完成步骤。";
  $("library-content").innerHTML='<p class="quiet">正在加载…</p>';$("library").showModal();
  try{
    const items=examples?await api("/api/examples"):await api("/api/runs");
    $("library-content").innerHTML=items.length?items.map(item=>'<button class="library-item" data-id="'+escape(examples?item.id:item.run_id)+'"><div><strong>'+escape(examples?item.id:item.request.topic||"未填写主题")+'</strong><small>'+escape(item.backend==="real"?"真实模型":"离线 Mock")+' / '+escape(examples?item.topic:item.run_id.slice(0,12))+'</small></div>'+badge(item.status)+'</button>').join(""):'<p class="quiet">还没有运行记录。创建一个任务后会保存在这里。</p>';
    $("library-content").querySelectorAll("[data-id]").forEach(button=>button.addEventListener("click",()=>{$("library").close();setTab("flow");openRun(button.dataset.id,examples);}));
  }catch(error){$("library-content").textContent=error.message;}
}
$("examples-open").addEventListener("click",()=>showLibrary(true));$("history-nav").addEventListener("click",()=>showLibrary(false));
$("workspace-nav").addEventListener("click",()=>document.querySelector(".workspace").scrollIntoView({behavior:"instant"}));
$("library-close").addEventListener("click",()=>$("library").close());
function download(value,filename,type){
  const url=URL.createObjectURL(new Blob([value],{type}));const a=document.createElement("a");a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$("download-button").addEventListener("click",()=>{if(current)download(JSON.stringify(current,null,2),current.run_id+".json","application/json");});
$("download-trace").addEventListener("click",()=>{if(current)download(current.events.map(e=>JSON.stringify(e)).join("\n")+"\n",current.run_id+"-trace.jsonl","application/x-ndjson");});
for(const id of["budget","deadline"])$(id).addEventListener("input",()=>{if(!current)render(null);});
async function init(){
  render(null);
  try{config=await api("/api/config");$("backend").querySelector('[value="real"]').disabled=!config.real_available;$("backend").querySelector('[value="real"]').textContent=config.real_available?config.model:"DeepSeek Pro（服务端未配置密钥）";updateMode();await refreshHistory();}
  catch(error){notify("无法连接本地服务，请使用 python -m src.web 启动工作台。");}
}
init();
