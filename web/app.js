const stages=[
["01","Intent","Agent requests a service"],
["02","Quote","Price + allowed scope"],
["03","Authority","Policy + limits"],
["04","Settlement","USDC on Base"],
["05","Execution","Service runs"],
["06","Observation","Independent check"],
["07","Proof","Evidence verified"]
];
let currentProof=null,currentOutcome=null;
const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const short=(v,n=24)=>{v=String(v??"");return v.length>n?v.slice(0,n)+"…":v};

function drawTimeline(mode="idle"){
  $("#timeline").innerHTML=stages.map((s,i)=>{
    let cls="route-step";
    if(mode==="ok") cls+=" pass";
    if(mode==="deny"){if(i<2)cls+=" pass";else if(i===2)cls+=" denied";}
    return '<article class="'+cls+'"><div class="orb"><span>'+s[0]+'</span></div><small>['+s[0]+']</small><b>'+s[1]+'</b><p>'+s[2]+'</p></article>';
  }).join("");
}
drawTimeline();

function setChecks(mode,p){
  const items=[...$("#monitor-checks").children];
  items.forEach(x=>x.className="");
  $("#monitor-state").style.color="";
  $("#open-evidence").disabled=mode==="idle";
  if(mode==="idle"){
    $("#monitor-state").textContent="READY";
    $("#monitor-root").textContent="awaiting transaction";
    $("#decision-value").textContent="WAITING";
    $("#bus-state").textContent="IDLE";
    return;
  }
  if(mode==="deny"){
    $("#monitor-state").textContent="DENIED";
    $("#monitor-state").style.color="var(--red)";
    $("#monitor-root").textContent=short(p?.proof_hash||"policy denied",30);
    items[0].className="fail";
    $("#decision-value").textContent="DENY";
    $("#bus-state").textContent="STOPPED";
    return;
  }
  $("#monitor-state").textContent="VERIFIED";
  $("#monitor-state").style.color="var(--green)";
  $("#monitor-root").textContent=short(p?.proof_hash,30);
  items.forEach(x=>x.className="pass");
  $("#decision-value").textContent="PERMIT";
  $("#bus-state").textContent="VERIFIED";
}

function busUpdate(p,denied){
  const lines=denied?[
    ["00","intent captured"],
    ["01","quote received"],
    ["02","authority denied"],
    ["03","settlement channel never opened"]
  ]:[
    ["00","intent "+short(p.intent?.intent_id,18)],
    ["01","quote "+short(p.quote?.quote_id,18)],
    ["02","authority PERMIT"],
    ["03","proof "+short(p.proof_hash,18)]
  ];
  $("#bus-lines").innerHTML=lines.map(x=>'<p><span>'+esc(x[0])+'</span>'+esc(x[1])+'</p>').join("");
}

async function run(amount){
  document.body.classList.add("busy");
  drawTimeline();
  setChecks("idle");
  $("#bus-lines").innerHTML='<p><span>..</span> evaluating request</p><p><span>..</span> checking policy</p><p><span>..</span> waiting for decision</p>';
  try{
    const r=await fetch("/api/run",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({
      amount_atomic:amount,
      document:"Autonomous agents can purchase digital services. AgentPay Proof constrains payment authority and independently verifies the outcome. Evidence should not depend on the purchasing agent's own claims."
    })});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||"request failed");
    currentOutcome=d;currentProof=d.proof;
    const denied=d.status==="DENIED";
    drawTimeline(denied?"deny":"ok");
    setChecks(denied?"deny":"ok",d.proof);
    busUpdate(d.proof,denied);
  }catch(e){
    $("#monitor-state").textContent="ERROR";$("#monitor-state").style.color="var(--red)";
    $("#bus-lines").innerHTML='<p><span>!!</span>'+esc(e.message)+'</p>';
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
  return rows.filter(r=>r[1]!=null).map(r=>'<article class="evidence-card"><small>'+esc(r[0])+'</small><strong title="'+esc(r[1])+'">'+esc(short(r[1],24))+'</strong><p>'+esc(r[2]||"")+'</p></article>').join("");
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
  const items=[...$("#monitor-checks").children];items.forEach(x=>x.className="fail");
  $("#bus-state").textContent="TAMPER DETECTED";
}

$("#run-ok").onclick=()=>run(250000);
$("#run-deny").onclick=()=>run(2000000);
$("#open-evidence").onclick=openEvidence;
$("#download-proof").onclick=downloadProof;
$("#tamper-proof").onclick=tamperProof;

/* Continuous data river with no loop boundary: particles wrap independently. */
(()=>{
  const c=$("#flow-canvas"),ctx=c.getContext("2d",{alpha:true});
  let w=0,h=0,dpr=1,start=performance.now(),parts=[];
  function seeded(i){const x=Math.sin(i*999.91)*43758.5453;return x-Math.floor(x)}
  function resize(){
    dpr=Math.min(devicePixelRatio||1,2);w=innerWidth;h=innerHeight;
    c.width=Math.round(w*dpr);c.height=Math.round(h*dpr);c.style.width=w+"px";c.style.height=h+"px";ctx.setTransform(dpr,0,0,dpr,0,0);
    const count=Math.max(70,Math.min(160,Math.floor(w/9)));
    parts=Array.from({length:count},(_,i)=>({
      base:seeded(i+1)*(w+240)-120,
      lane:(seeded(i+91)-.5)*150,
      speed:24+seeded(i+211)*70,
      size:.6+seeded(i+321)*1.5,
      phase:seeded(i+401)*Math.PI*2
    }));
  }
  function pathY(x,t,lane){
    return h*.43+Math.sin(x*.006+t*.00042)*34+Math.sin(x*.013-t*.00019)*10+lane;
  }
  function frame(now){
    const elapsed=(now-start)/1000;
    ctx.clearRect(0,0,w,h);
    for(let k=-2;k<=2;k++){
      ctx.beginPath();
      for(let x=-30;x<=w+30;x+=16){
        const y=pathY(x,now,k*13);
        if(x===-30)ctx.moveTo(x,y);else ctx.lineTo(x,y);
      }
      const a=k===0?.24:.08;
      ctx.strokeStyle=k===0?"rgba(190,232,255,"+a+")":"rgba(40,145,255,"+a+")";
      ctx.lineWidth=k===0?1.4:.7;ctx.stroke();
    }
    for(const p of parts){
      const span=w+260;
      const x=((p.base+elapsed*p.speed+120)%span)-120;
      const y=pathY(x,now,p.lane*.32+Math.sin(p.phase+elapsed*.7)*10);
      ctx.fillStyle=p.size>1.5?"rgba(220,244,255,.62)":"rgba(40,145,255,.38)";
      ctx.fillRect(x,y,p.size*1.6,p.size*1.6);
    }
    requestAnimationFrame(frame);
  }
  addEventListener("resize",resize,{passive:true});resize();
  if(!matchMedia("(prefers-reduced-motion: reduce)").matches)requestAnimationFrame(frame);
})();