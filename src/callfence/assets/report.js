"use strict";
const report=JSON.parse(document.getElementById("report-data").textContent);
const latest=report.runs.length-1;
const cases=report.runs[latest].cases;
const changes=new Map((report.changes||cases.map(c=>({id:c.id,effect:c.status==="passed"?"stable":c.status==="blocked"?"needs_review":"existing_failure"}))).map(c=>[c.id,c]));
const effectLabels={regression:"New failure",fixed:"Fixed",stable:"Stable",existing_failure:"Existing failure",needs_review:"Need review"};
let selected=cases[0].id,snapshot=latest;
const el=id=>document.getElementById(id);
const make=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;};
const tag=(value,label)=>make("span","tag "+value,label||value);
el("consumer").textContent=report.consumer;
el("run-id").textContent="RUN / "+report.run_id.slice(0,12);
el("count-cases").textContent=cases.length;
el("count-regressions").textContent=report.change_summary?report.change_summary.regression:report.runs[latest].summary.failed;
if(!report.change_summary)el("regression-label").textContent="Failed samples";
el("count-blocked").textContent=report.change_summary?report.change_summary.needs_review:report.runs[latest].summary.blocked;
el("count-passed").textContent=report.runs[latest].summary.passed;
el("scope").textContent=report.scope;
report.runs.forEach((run,index)=>{const node=make("div","source");node.append(make("strong","",(report.mode==="compare"?(index?"CANDIDATE":"BASELINE"):"SPECIFICATION")+" / "+run.spec.file),make("div","mono",run.spec.title+" · "+run.spec.version+" · SHA256 "+run.spec.sha256.slice(0,12)));el("sources").append(node);});
const source=make("div","source");source.append(make("strong","","CLIENT / "+report.client.file),make("div","mono","SHA256 "+report.client.sha256.slice(0,12)));el("sources").append(source);
const blob=new Blob([JSON.stringify(report,null,2)],{type:"application/json"});
el("json-download").href=URL.createObjectURL(blob);
function evidence(value,label){const box=make("div","evidence");box.append(make("p","eyebrow",label),make("code","",value.file+"#"+value.pointer),make("pre","",value.present?JSON.stringify(value.value,null,2):"Not present in this source"));return box;}
function details(){const item=report.runs[snapshot].cases.find(c=>c.id===selected);const change=changes.get(selected);el("case-title").textContent=item.title;el("case-route").textContent=item.method+" "+item.path;el("case-outcome").replaceChildren(tag(change.effect,effectLabels[change.effect]));if(report.mode==="compare")el("case-outcome").append(make("span","muted",change.before+" → "+change.after));el("snapshot-controls").hidden=report.mode!=="compare";el("before").setAttribute("aria-pressed",snapshot===0);el("after").setAttribute("aria-pressed",snapshot===latest);el("finding-summary").textContent=(report.mode==="compare"?(snapshot===0?"Baseline":"Candidate"):"Specification")+": "+item.status+" · "+item.findings.length+" findings";el("findings").replaceChildren();const priority={failed:0,blocked:1,passed:2};[...item.findings].sort((a,b)=>priority[a.level]-priority[b.level]).forEach(f=>{const node=make("section","finding");const head=make("div","finding-head");head.append(tag(f.level),make("code","",f.code));node.append(head,make("p","",f.message));const grid=make("div","evidence-grid");grid.append(evidence(f.client,"Client request"),evidence(f.server,"Server declaration"));node.append(grid);f.references.forEach(ref=>node.append(make("p","reference","Local reference: "+ref.from+" → "+ref.to)));el("findings").append(node);});}
function listing(){const query=el("search").value.toLowerCase(),filter=el("filter").value;const visible=cases.filter(c=>(filter==="all"||changes.get(c.id).effect===filter)&&(c.id+" "+c.title+" "+c.path+" "+c.method).toLowerCase().includes(query));if(visible.length&&!visible.some(c=>c.id===selected))selected=visible[0].id;el("case-list").replaceChildren();el("case-count").textContent=visible.length+" of "+cases.length+" cases";visible.forEach(c=>{const button=make("button","case-button");button.type="button";button.setAttribute("aria-pressed",c.id===selected);const row=make("span","case-title-row");row.append(make("span","",c.title),tag(changes.get(c.id).effect,effectLabels[changes.get(c.id).effect]));button.append(row,make("span","route",c.method+" "+c.path));button.addEventListener("click",()=>{selected=c.id;listing();});const wrapper=make("div");wrapper.setAttribute("role","listitem");wrapper.append(button);el("case-list").append(wrapper);});if(!visible.length)el("case-list").append(make("p","muted","No request cases match these filters."));details();}
el("search").addEventListener("input",listing);el("filter").addEventListener("change",listing);el("before").addEventListener("click",()=>{snapshot=0;details();});el("after").addEventListener("click",()=>{snapshot=latest;details();});listing();
