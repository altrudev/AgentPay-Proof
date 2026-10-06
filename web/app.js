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
let connectedAccount=null;
const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const short=(v,n=20)=>{v=String(v??"");return v.length>n?v.slice(0,n)+"…":v};
function fitStage(){
 const stage=document.querySelector(".shell");
 const scale=Math.min(innerWidth/1672,innerHeight/941);
 stage.style.transform="translate(-50%,-50%) scale("+scale+")";
}
function showStatus(title,message,actions=[]){
 $("#status-title").textContent=title;
 $("#status-message").textContent=message;
 const box=$("#status-actions");box.innerHTML="";
 for(const action of actions){
  const b=document.createElement("button");b.type="button";b.textContent=action.label;
  b.onclick=()=>{if(action.onClick)action.onClick();$("#status-dialog").close()};
  box.appendChild(b)
 }
 $("#status-dialog").showModal()
}
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
async function connectWallet(){
 if(!window.ethereum){
  showStatus("Wallet not detected","No injected EVM wallet is available in this browser profile. Install or enable MetaMask, Coinbase Wallet, or another Base-compatible browser wallet, allow it on this site, then refresh.");
  return null
 }
 try{
  const accounts=await ethereum.request({method:"eth_requestAccounts"});
  connectedAccount=accounts?.[0]||null;
  if(connectedAccount){
   $("#wallet-state").textContent=short(connectedAccount,12);
   $("#runtime-state").textContent="Wallet ready";
  }
  return connectedAccount
 }catch(e){
  showStatus("Wallet connection stopped",e?.code===4001?"You rejected the wallet connection request.":(e?.message||"Wallet connection failed."));
  return null
 }
}
async function runLive(){
 if(!liveConfig.enabled){
  showStatus("Live mode unavailable","The live Base settlement configuration is not enabled on this server.");
  return
 }
 const account=connectedAccount||await connectWallet();
 if(!account)return;
 document.body.classList.add("running");draw();
 const document="Autonomous agents can purchase digital services. AgentPay Proof constrains payment authority and independently verifies the outcome. Evidence should not depend on the purchasing agent's own claims.";
 let prepared=null;
 try{
  prepared=await postJson("/api/live/prepare",{amount_atomic:250000,document});
  if(prepared.status==="DENIED"){
   currentProof=prepared.proof;draw("deny");addActivity("AgentPay Live","Denied (policy)","—","bad");return
  }
  const sender=connectedAccount||account;
  if(!sender)throw new Error("wallet-account-required");
  try{
   await ethereum.request({method:"wallet_switchEthereumChain",params:[{chainId:prepared.wallet_request.chainId}]})
  }catch(e){
   if(e?.code===4902){
    await ethereum.request({method:"wallet_addEthereumChain",params:[{
     chainId:prepared.wallet_request.chainId,
     chainName:"Base",
     nativeCurrency:{name:"Ether",symbol:"ETH",decimals:18},
     rpcUrls:["https://mainnet.base.org"],
     blockExplorerUrls:["https://basescan.org"]
    }]})
   }else{throw e}
  }
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
  const msg=e?.code===4001?"You rejected the wallet request. No payment was sent.":(e?.message||"Live payment failed.");
  showStatus("Live payment stopped",msg);
 }finally{document.body.classList.remove("running")}
}
async function refreshNetworkStatus(){
 try{
  const r=await fetch("/api/live/network");
  const d=await r.json();
  if(!r.ok||!d.online)throw new Error(d.error||"rpc-unavailable");
  $("#network-block").textContent=String(d.block);
  $("#network-gas").textContent=String(d.gas_gwei)+" gwei";
  $("#network-rpc").textContent=String(d.rpc_ms)+" ms";
  if(!connectedAccount)$("#runtime-state").textContent="Online";
 }catch(e){
  $("#network-block").textContent="—";
  $("#network-gas").textContent="—";
  $("#network-rpc").textContent="—";
  if(!connectedAccount)$("#runtime-state").textContent="RPC offline";
 }
}
async function initRuntime(){
 try{
  const r=await fetch("/api/live/config"),d=await r.json();liveConfig=d;
  $("#runtime-network").textContent=d.enabled?"Base Mainnet":"Demo";
  $("#network-label").textContent=d.enabled?"Base Mainnet":"Demo / Base";
  $("#runtime-state").textContent=d.enabled?"Online":"Demo";
  if(window.ethereum){
   try{
    const accounts=await ethereum.request({method:"eth_accounts"});
    connectedAccount=accounts?.[0]||null;
    $("#wallet-state").textContent=connectedAccount?short(connectedAccount,12):"Not connected";
    if(connectedAccount)$("#runtime-state").textContent="Wallet ready";
   }catch(e){console.error(e)}
   ethereum.on?.("accountsChanged",accounts=>{
    connectedAccount=accounts?.[0]||null;
    $("#wallet-state").textContent=connectedAccount?short(connectedAccount,12):"Not connected";
    $("#runtime-state").textContent=connectedAccount?"Wallet ready":"Online";
   });
  }
  if(d.enabled)refreshNetworkStatus();
 }catch(e){
  console.error(e);
  $("#runtime-state").textContent="Unavailable";
 }
}
$("#run-service").onclick=()=>runLive();
$("#network-control").onclick=()=>connectWallet();
$("#nav-run").onclick=e=>{e.preventDefault();runLive()};
$("#nav-proofs").onclick=e=>{e.preventDefault();if(currentProof)openEvidence();else showStatus("No proof yet","Run a service first. A verified proof will appear here.")};
$("#search-control").onclick=()=>showStatus("Search","Service search is not part of this competition vertical slice.");
$("#theme-control").onclick=()=>document.body.classList.toggle("dim");
$("#menu-control").onclick=()=>showStatus("AgentPay Proof","Use Run a Service for the governed live flow. The Base selector also connects your wallet.");
initRuntime();
fitStage();
addEventListener("resize",fitStage,{passive:true});
$("#explore").onclick=()=>document.querySelector(".services").animate([{boxShadow:"0 0 0 rgba(21,151,255,0)"},{boxShadow:"0 0 42px rgba(21,151,255,.42)"},{boxShadow:"0 0 0 rgba(21,151,255,0)"}],{duration:900});

