const stages=[
["01","Intent","Agent requests a service","doc"],
["02","Quote","Get price and allowed scope","sliders"],
["03","Authority","Verify policy and limits","shield"],
["04","Settlement","USDC transaction on Base","coin"],
["05","Execution","Service runs in boundary","code"],
["06","Observation","Independent verification","eye"],
["07","Proof","Get verifiable evidence","hash"]
];
let currentProof=null;
let liveConfig={enabled:false};
const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const short=(v,n=20)=>{v=String(v??"");return v.length>n?v.slice(0,n)+"…":v};
const icon=name=>{
 const path={
  doc:'<path d="M8 4h10l6 6v18H8z"/><path d="M18 4v7h6"/><path d="M12 17h8M12 21h8"/>',
  sliders:'<path d="M6 9h20M6 16h20M6 23h20"/><circle cx="12" cy="9" r="2.5"/><circle cx="21" cy="16" r="2.5"/><circle cx="15" cy="23" r="2.5"/>',
  shield:'<path d="M16 4 26 8v7c0 7-4.4 11-10 14-5.6-3-10-7-10-14V8z"/><path d="m12 16 3 3 6-7"/>',
  coin:'<ellipse cx="16" cy="9" rx="8" ry="4"/><path d="M8 9v6c0 2 3.6 4 8 4s8-2 8-4V9M8 15v6c0 2 3.6 4 8 4s8-2 8-4v-6"/>',
  code:'<path d="m11 10-6 6 6 6M21 10l6 6-6 6M18 6l-4 20"/>',
  eye:'<path d="M3 16s5-8 13-8 13 8 13 8-5 8-13 8S3 16 3 16Z"/><circle cx="16" cy="16" r="4"/>',
  hash:'<path d="M11 4 8 28M22 4l-3 24M5 12h22M4 21h22"/>'
 }[name];
 return '<svg viewBox="0 0 32 32" aria-hidden="true">'+path+'</svg>'
};
function draw(mode="idle",upto=99){
 $("#timeline").innerHTML=stages.map((s,i)=>{let c="step";if(mode==="ok"&&i<=upto)c+=" pass";if(mode==="deny"){if(i<2)c+=" pass";else if(i===2)c+=" denied"}return '<article class="'+c+'" data-stage="'+i+'"><div class="step-icon">'+icon(s[3])+'</div><small>['+s[0]+']</small><b>'+s[1]+'</b><p>'+s[2]+'</p></article>'}).join("");
 const proof=document.querySelector('.step[data-stage="6"]');if(proof&&currentProof)proof.onclick=openEvidence
}
draw();
async function run(amount){
 document.body.classList.add("running");draw();
 try{
  const r=await fetch("/api/run",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({amount_atomic:amount,document:"Autonomous agents can purchase digital services. AgentPay Proof constrains payment authority and independently verifies the outcome. Evidence should not depend on the purchasing agent's own claims."})});
  const d=await r.json();if(!r.ok)throw new Error(d.error||"request failed");currentProof=d.proof;const denied=d.status==="DENIED";
  if(denied){draw("deny")}else{for(let i=0;i<7;i++){draw("ok",i);await new Promise(resolve=>setTimeout(resolve,110))}}
  addActivity("AgentPay Demo",denied?"Denied (policy)":"Verified",denied?"—":"0.25 USDC",denied?"bad":"ok");
 }catch(e){console.error(e)}finally{document.body.classList.remove("running")}
}
function openEvidence(){
 if(!currentProof)return;
 const p=currentProof,rows=[["Intent",p.intent?.intent_id],["Quote",p.quote?.quote_id],["Authority",p.authority?.decision],["Settlement",p.settlement?.transaction_hash],["Execution",p.result?.result_digest],["Observation",p.observation?.observer_id],["Proof",p.proof_hash]];
 $("#evidence-grid").innerHTML=rows.filter(x=>x[1]).map(x=>'<article><small>'+esc(x[0])+'</small><div>'+esc(short(x[1],22))+'</div></article>').join("");
 $("#evidence-json").textContent=JSON.stringify(p,null,2);$("#evidence-dialog").showModal()
}
async function postJson(path,payload){
 const r=await fetch(path,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
 const d=await r.json();if(!r.ok){const e=new Error(d.error||"request failed");e.status=r.status;e.payload=d;throw e}return d
}
function addActivity(name,status,amount="—",kind="info"){
 const list=$("#activity-list"),row=document.createElement("p");
 row.innerHTML='<i class="'+kind+'"></i><b>'+esc(name)+'</b><em>'+esc(status)+'</em><span>'+esc(amount)+'</span><small>now</small>';
 list.prepend(row);while(list.children.length>5)list.lastElementChild.remove()
}
async function reconcileLive(decisionId,txHash,sender){
 for(let attempt=0;attempt<30;attempt++){
  try{return await postJson("/api/live/reconcile",{decision_id:decisionId,transaction_hash:txHash,sender})}
  catch(e){
   if(e.status===409&&e.payload?.error==="settlement-not-observed"){
    $("#runtime-state").textContent="Reconciling";await new Promise(r=>setTimeout(r,2000));continue
   }
   throw e
  }
 }
 throw new Error("settlement-reconciliation-timeout")
}
async function runLive(){
 if(!liveConfig.enabled)throw new Error("live-mode-not-configured");
 if(!window.ethereum)throw new Error("browser-wallet-required");
 document.body.classList.add("running");draw();
 const document="Autonomous agents can purchase digital services. AgentPay Proof constrains payment authority and independently verifies the outcome. Evidence should not depend on the purchasing agent's own claims.";
 let prepared=null;
 try{
  prepared=await postJson("/api/live/prepare",{amount_atomic:250000,document});
  if(prepared.status==="DENIED"){
   currentProof=prepared.proof;draw("deny");addActivity("AgentPay Live","Denied (policy)","—","bad");return
  }
  const accounts=await ethereum.request({method:"eth_requestAccounts"});
  if(!accounts?.[0])throw new Error("wallet-account-required");
  const sender=accounts[0];
  await ethereum.request({method:"wallet_switchEthereumChain",params:[{chainId:prepared.wallet_request.chainId}]});
  $("#runtime-state").textContent="Wallet approval";
  let txHash;
  try{
   txHash=await ethereum.request({method:"eth_sendTransaction",params:[{
    from:sender,to:prepared.wallet_request.to,value:prepared.wallet_request.value,data:prepared.wallet_request.data
   }]});
  }catch(e){
   if(e?.code===4001){
    await postJson("/api/live/abort",{decision_id:prepared.decision_id});
    addActivity("AgentPay Live","Wallet rejected","—","bad");
   }else{
    await postJson("/api/live/uncertain",{decision_id:prepared.decision_id}).catch(()=>{});
    addActivity("AgentPay Live","In doubt","—","info");
   }
   throw e
  }
  $("#runtime-state").textContent="Observing chain";
  const result=await reconcileLive(prepared.decision_id,txHash,sender);
  currentProof=result.proof;
  for(let i=0;i<7;i++){draw("ok",i);await new Promise(resolve=>setTimeout(resolve,110))}
  addActivity("AgentPay Live","Verified","0.25 USDC","ok");
  $("#runtime-state").textContent="Verified";
 }catch(e){
  console.error(e);
  if($("#runtime-state").textContent!=="Verified")$("#runtime-state").textContent="Attention";
 }finally{document.body.classList.remove("running")}
}
async function initRuntime(){
 try{
  const r=await fetch("/api/live/config"),d=await r.json();liveConfig=d;
  $("#live-enabled").textContent=d.enabled?"Enabled":"Not configured";
  $("#runtime-network").textContent=d.enabled?"Base chain "+d.chain_id:"Demo";
  $("#network-label").textContent=d.enabled?"Base "+d.chain_id:"Demo / Base";
  $("#run-live").hidden=!d.enabled;
 }catch(e){console.error(e)}
}
$("#run-ok").onclick=()=>run(250000);
$("#run-live").onclick=()=>runLive();
initRuntime();
$("#explore").onclick=()=>document.querySelector(".services").animate([{boxShadow:"0 0 0 rgba(21,151,255,0)"},{boxShadow:"0 0 42px rgba(21,151,255,.42)"},{boxShadow:"0 0 0 rgba(21,151,255,0)"}],{duration:900});

(()=>{
 const c=$("#scene"),g=c.getContext("2d",{alpha:false,desynchronized:true});
 let w=0,h=0,dpr=1,start=performance.now(),bits=[],stars=[],ridges=[];
 const rand=i=>{const n=Math.sin(i*131.73+17.91)*43758.5453123;return n-Math.floor(n)};
 function resize(){
  dpr=Math.min(devicePixelRatio||1,3);w=innerWidth;h=innerHeight;
  c.width=Math.max(1,Math.round(w*dpr));c.height=Math.max(1,Math.round(h*dpr));c.style.width=w+"px";c.style.height=h+"px";g.setTransform(dpr,0,0,dpr,0,0);
  bits=Array.from({length:900},(_,i)=>({base:rand(i)*(w+460)-230,lane:(rand(i+700)-.5)*250,speed:30+rand(i+1200)*150,size:.35+rand(i+1800)*1.75,phase:rand(i+2400)*6.283,tone:rand(i+3100)}));
  stars=Array.from({length:1500},(_,i)=>({x:rand(i+4100)*w,y:rand(i+5200)*h*.72,a:.025+rand(i+6100)*.48,size:.25+rand(i+7000)*1.4}));
  ridges=[0,1,2,3].map(layer=>Array.from({length:96},(_,i)=>{
   const x=w*(.26+i/95*.78),noise=rand(i+layer*257),n2=rand(i*7+layer*997);
   const arch=Math.pow(Math.sin(Math.PI*i/95),.55);
   const y=h*(.43-layer*.018)-arch*h*(.11+layer*.016)-(noise*.62+n2*.38)*h*(.06+layer*.012);
   return [x,y]
  }))
 }
 function riverY(x,t,lane=0){return h*.445+Math.sin(x*.006+t*.00034)*42+Math.sin(x*.014-t*.00017)*15+lane}
 function drawSky(now){
  const bg=g.createLinearGradient(0,0,0,h);bg.addColorStop(0,"#071a2a");bg.addColorStop(.46,"#04111d");bg.addColorStop(1,"#020812");g.fillStyle=bg;g.fillRect(0,0,w,h);
  const halo=g.createRadialGradient(w*.72,h*.25,20,w*.72,h*.25,w*.45);halo.addColorStop(0,"rgba(43,143,226,.22)");halo.addColorStop(.48,"rgba(14,72,128,.09)");halo.addColorStop(1,"rgba(0,0,0,0)");g.fillStyle=halo;g.fillRect(0,0,w,h);
  for(const p of stars){g.fillStyle='rgba(52,164,250,'+p.a+')';g.fillRect(p.x,p.y,p.size,p.size)}
 }
 function drawMist(){
  const blobs=[[.48,.27,.18,.11],[.60,.24,.15,.10],[.74,.22,.17,.12],[.86,.26,.14,.09]];
  for(const [bx,by,rx,a] of blobs){
    const gr=g.createRadialGradient(w*bx,h*by,0,w*bx,h*by,w*rx);
    gr.addColorStop(0,'rgba(165,208,235,'+a+')');gr.addColorStop(.45,'rgba(55,106,145,'+(a*.42)+')');gr.addColorStop(1,'rgba(0,0,0,0)');
    g.fillStyle=gr;g.fillRect(w*(bx-rx),h*(by-rx),w*rx*2,h*rx*2);
  }
 }
 function drawMountains(){
  for(let layer=0;layer<ridges.length;layer++){
   const r=ridges[layer],base=h*.565+layer*10;
   g.beginPath();g.moveTo(r[0][0],base);for(const [x,y] of r)g.lineTo(x,y);g.lineTo(r[r.length-1][0],base);g.closePath();
   const grad=g.createLinearGradient(0,h*.16,0,h*.59);
   grad.addColorStop(0,'rgba('+(layer>1?'23,74,115':'14,52,82')+','+(.42+layer*.06)+')');
   grad.addColorStop(.68,'rgba(5,28,48,'+(.64+layer*.04)+')');
   grad.addColorStop(1,'rgba(2,10,18,.10)');
   g.fillStyle=grad;g.fill();
   g.strokeStyle='rgba('+(layer===3?'220,244,255':'86,171,230')+','+(.22+layer*.12)+')';g.lineWidth=layer===3?1.6:.8;g.stroke();
   g.save();g.globalCompositeOperation="lighter";
   for(let i=2;i<r.length-2;i++){
     const [x,y]=r[i],py=r[i-1][1],ny=r[i+1][1];
     if(i%2===0 && y<py && y<ny){
       g.strokeStyle='rgba(242,251,255,'+(layer===3?.72:.28)+')';g.lineWidth=layer===3?1.1:.65;
       g.beginPath();g.moveTo(x,y);g.lineTo(x-16,y+23);g.moveTo(x,y);g.lineTo(x+19,y+27);g.stroke();
     }
     if(i%3===0){const z=rand(i+layer*37)>.62?1.7:1.05;g.fillStyle=z>1.5?'rgba(229,248,255,.78)':'rgba(30,155,248,.58)';g.fillRect(x-1,y+12+rand(i+layer*53)*42,z,z)}
   }
   g.restore()
  }
 }
 function drawMesh(now){
  for(let row=0;row<11;row++){g.beginPath();for(let x=w*.18;x<w+20;x+=13){const y=h*(.33+row*.026)+Math.sin(x*.0061+row*1.7+now*.00006)*17+Math.sin(x*.018-row*.75)*6;x===w*.18?g.moveTo(x,y):g.lineTo(x,y)}g.strokeStyle='rgba(48,130,196,'+(.035+row*.009)+')';g.lineWidth=.55;g.stroke()}
  for(let x=w*.2;x<w;x+=28){g.strokeStyle="rgba(55,137,202,.05)";g.beginPath();g.moveTo(x,h*.3);g.lineTo(x+130,h*.59);g.stroke()}
 }
 function drawWeave(now){
  const x0=w*.70,top=h*.04,join=h*.40;
  g.save();g.globalCompositeOperation="lighter";
  for(let k=-11;k<=11;k++){const x=x0+k*4.7;g.beginPath();g.moveTo(x,top);g.bezierCurveTo(x+Math.sin(now*.00024+k)*26,h*.18,x-34,h*.30,w*.70,join);g.bezierCurveTo(w*.68,h*.42,w*.74,h*.44,w*.81,h*.462);g.strokeStyle=k%4===0?"rgba(244,251,255,.27)":"rgba(23,151,255,.17)";g.lineWidth=k%4===0?1.25:.68;g.stroke()}
  for(let y=h*.07;y<h*.39;y+=18){g.strokeStyle="rgba(91,218,255,.18)";g.beginPath();g.moveTo(x0-45,y);g.lineTo(x0+45,y+28);g.moveTo(x0+45,y);g.lineTo(x0-45,y+28);g.stroke()}
  g.restore()
 }
 function drawRiver(now,elapsed){
  g.save();g.globalCompositeOperation="lighter";
  for(let k=-12;k<=12;k++){
    g.beginPath();for(let x=w*.11;x<w+80;x+=7){const y=riverY(x,now,k*6.0);x===w*.11?g.moveTo(x,y):g.lineTo(x,y)}
    const edge=Math.abs(k)/12,a=.035+(1-edge)*.17;
    if(Math.abs(k)<=3){g.strokeStyle='rgba(32,145,255,'+(0.035+(3-Math.abs(k))*.018)+')';g.lineWidth=9-Math.abs(k)*1.7;g.stroke();g.beginPath();for(let x=w*.11;x<w+80;x+=7){const y=riverY(x,now,k*6.0);x===w*.11?g.moveTo(x,y):g.lineTo(x,y)}}
    g.strokeStyle=k===0?"rgba(250,253,255,.98)":'rgba('+(k%4===0?"101,222,255":"25,149,255")+','+a+')';g.lineWidth=k===0?2.8:(k%4===0?1.18:.56);g.stroke()
  }
  for(const p of bits){
    const span=w+460,x=((p.base+elapsed*p.speed+230)%span)-230,y=riverY(x,now,p.lane*.42+Math.sin(elapsed*.8+p.phase)*9);
    const bright=p.tone>.76;g.fillStyle=bright?"rgba(236,250,255,.94)":"rgba(29,157,255,.70)";
    const z=bright?p.size*2.05:p.size*1.65;g.fillRect(x,y,z,z);
    if(p.tone>.94){g.strokeStyle='rgba(104,224,255,.55)';g.strokeRect(x-2,y-2,z+4,z+4)}
  }g.restore()
 }
 function frame(now){const elapsed=(now-start)/1000;drawSky(now);drawMist();drawMountains();drawMesh(now);drawWeave(now);drawRiver(now,elapsed);requestAnimationFrame(frame)}
 addEventListener("resize",resize,{passive:true});resize();if(!matchMedia("(prefers-reduced-motion: reduce)").matches)requestAnimationFrame(frame)
})();