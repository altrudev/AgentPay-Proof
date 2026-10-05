const stages=[
  ["01","Intent","Agent requests a service"],
  ["02","Quote","Get price and allowed scope"],
  ["03","Authority","Verify policy and limits"],
  ["04","Settlement","USDC transaction on Base"],
  ["05","Execution","Service runs in boundary"],
  ["06","Observation","Independent verification"],
  ["07","Proof","Get verifiable evidence"]
];

let currentProof=null,currentOutcome=null;
const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const short=(v,n=22)=>{v=String(v??"");return v.length>n?v.slice(0,n)+"…":v};

function paintTimeline(mode="idle"){
  $("#timeline").innerHTML=stages.map((s,i)=>{
    let cls="stage";
    if(mode==="ok") cls+=" pass";
    if(mode==="deny"){if(i<2)cls+=" pass";else if(i===2)cls+=" denied";}
    return '<article class="'+cls+'"><div class="stage-orb"><span>'+s[0]+'</span></div><small>['+s[0]+']</small><h3>'+s[1]+'</h3><p>'+s[2]+'</p></article>';
  }).join("");
}
paintTimeline();

function setMonitor(mode,p){
  const state=$("#monitor-state"),root=$("#monitor-root"),items=[...$("#monitor-checks").children];
  items.forEach(x=>x.className="");
  if(mode==="idle"){state.textContent="READY";root.textContent="waiting for transaction";$("#open-evidence").disabled=true;return}
  if(mode==="deny"){
    state.textContent="DENIED";state.style.color="var(--red)";
    root.textContent=p?.proof_hash?short(p.proof_hash,30):"policy denied";
    items[0].className="fail";$("#open-evidence").disabled=false;return;
  }
  state.textContent="VERIFIED";state.style.color="var(--green)";
  root.textContent=short(p?.proof_hash,30);
  items.forEach(x=>x.className="pass");
  $("#open-evidence").disabled=false;
}

async function run(amount){
  document.body.classList.add("busy");
  paintTimeline();
  setMonitor("idle");
  $("#result").className="result-panel";
  $("#result").innerHTML="<span>CHECKING</span><p>Evaluating quote, policy and evidence boundary…</p>";
  try{
    const r=await fetch("/api/run",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({
      amount_atomic:amount,
      document:"Autonomous agents can purchase digital services. AgentPay Proof constrains payment authority and independently verifies the outcome. Evidence should not depend on the purchasing agent's own claims."
    })});
    const d=await r.json();
    if(!r.ok) throw new Error(d.error||"request failed");
    currentOutcome=d;currentProof=d.proof;
    const denied=d.status==="DENIED";
    paintTimeline(denied?"deny":"ok");
    setMonitor(denied?"deny":"ok",d.proof);
    $("#result").className="result-panel "+(denied?"deny":"ok");
    $("#result").innerHTML=denied
      ?"<span>DENIED</span><p>Purchase stopped at authority. $0 transferred and no transaction was created.</p>"
      :"<span>VERIFIED</span><p>Authorized route completed through execution, independent observation and proof verification.</p>";
  }catch(e){
    $("#result").className="result-panel deny";
    $("#result").innerHTML="<span>ERROR</span><p>"+esc(e.message)+"</p>";
  }finally{document.body.classList.remove("busy")}
}

function evidenceCards(p){
  const rows=[
    ["INTENT",p.intent?.intent_id,p.intent?.request_digest],
    ["QUOTE",p.quote?.quote_id,p.quote?.digest],
    ["AUTHORITY",p.authority?.decision,p.authority?.reason],
    ["SETTLEMENT",p.settlement?.transaction_hash,p.settlement?.status],
    ["EXECUTION",p.result?.result_digest,p.result?.status],
    ["OBSERVATION",p.observation?.observer_id,p.observation?.verdict],
    ["PROOF",p.proof_hash,"portable verification root"]
  ];
  return rows.filter(r=>r[1]!=null).map(r=>'<article class="evidence-card"><small>'+esc(r[0])+'</small><strong title="'+esc(r[1])+'">'+esc(short(r[1],25))+'</strong><p>'+esc(r[2]||"")+'</p></article>').join("");
}

function openEvidence(){
  if(!currentProof)return;
  $("#evidence-grid").innerHTML=evidenceCards(currentProof);
  $("#evidence-json").textContent=JSON.stringify(currentProof,null,2);
  $("#tamper-proof").style.display=currentProof.settlement?"inline-block":"none";
  $("#evidence-dialog").showModal();
}
function downloadProof(){
  if(!currentProof)return;
  const b=new Blob([JSON.stringify(currentProof,null,2)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download="agentpay-proof.json";a.click();URL.revokeObjectURL(a.href);
}
async function tamperProof(){
  const r=await fetch("/api/tamper",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({proof:currentProof})});
  const d=await r.json();
  $("#evidence-json").textContent=JSON.stringify(d,null,2);
  $("#monitor-state").textContent="NOT VERIFIED";$("#monitor-state").style.color="var(--red)";
  $("#result").className="result-panel deny";
  $("#result").innerHTML="<span>NOT VERIFIED</span><p>Tampering detected. Modified evidence failed server-side verification.</p>";
}

$("#run-ok").onclick=()=>run(250000);
$("#run-deny").onclick=()=>run(2000000);
$("#open-evidence").onclick=openEvidence;
$("#download-proof").onclick=downloadProof;
$("#tamper-proof").onclick=tamperProof;

/* Living data river: deterministic low-cost Canvas animation. */
(()=>{
  const c=$("#flow-canvas"),ctx=c.getContext("2d",{alpha:true});
  let w=0,h=0,dpr=1,t=0,particles=[];
  function resize(){
    dpr=Math.min(window.devicePixelRatio||1,2);w=innerWidth;h=innerHeight;
    c.width=w*dpr;c.height=h*dpr;c.style.width=w+"px";c.style.height=h+"px";ctx.setTransform(dpr,0,0,dpr,0,0);
    particles=Array.from({length:Math.min(150,Math.floor(w/8))},(_,i)=>({x:Math.random()*w,y:Math.random()*h,s:.25+Math.random()*1.25,p:Math.random()*Math.PI*2,l:20+Math.random()*70}));
  }
  function flowY(x,phase){return h*.48+Math.sin(x*.006+phase)*45+Math.sin(x*.014-phase*.65)*14}
  function frame(){
    t+=.006;ctx.clearRect(0,0,w,h);
    const g=ctx.createLinearGradient(0,0,w,0);g.addColorStop(0,"rgba(0,80,180,0)");g.addColorStop(.2,"rgba(34,152,255,.22)");g.addColorStop(.55,"rgba(220,245,255,.34)");g.addColorStop(.8,"rgba(63,215,255,.18)");g.addColorStop(1,"rgba(0,80,180,0)");
    for(let k=0;k<5;k++){ctx.beginPath();for(let x=-20;x<w+20;x+=12){let y=flowY(x,t*6+k*.6)+(k-2)*9;if(x<0)ctx.moveTo(x,y);else ctx.lineTo(x,y)}ctx.strokeStyle=g;ctx.lineWidth=k===2?1.7:.55;ctx.stroke()}
    particles.forEach(q=>{q.x+=q.s;if(q.x>w+10)q.x=-10;q.y=flowY(q.x,t*6+q.p)+Math.sin(t*18+q.p)*q.l;ctx.fillStyle=q.s>.9?"rgba(195,235,255,.62)":"rgba(34,152,255,.35)";ctx.fillRect(q.x,q.y,q.s*1.4,q.s*1.4)});
    requestAnimationFrame(frame);
  }
  addEventListener("resize",resize,{passive:true});resize();
  if(!matchMedia("(prefers-reduced-motion: reduce)").matches)frame();
})();