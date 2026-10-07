const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const short=(v,n=20)=>{v=String(v??"");return v.length>n?v.slice(0,n)+"…":v};
const usdc=atomic=>(Number(atomic||0)/1_000_000).toFixed(2)+" USDC";

let liveConfig={enabled:false};
let connectedAccount=null;
let currentProof=null;
let currentArtifact=null;
let currentService=null;
let catalog=[];
let inProgress=false;
const SESSION_KEY="agentpay.activity.v1";

function fitStage(){
 const stage=$("#stage");
 const mobile=matchMedia("(max-width:900px)").matches;
 if(mobile){
  const scale=innerWidth/1672;
  stage.style.transform="scale("+scale+")";
  stage.style.transformOrigin="0 0";
  stage.style.left="0";stage.style.top="0";
  document.body.style.height=(940*scale)+"px";
  return;
 }
 const scale=Math.min(innerWidth/1672,innerHeight/940);
 stage.style.left="50%";stage.style.top="50%";
 stage.style.transformOrigin="center center";
 stage.style.transform="translate(-50%,-50%) scale("+scale+")";
 document.body.style.height="";
}
addEventListener("resize",fitStage,{passive:true});
fitStage();

function chainName(chainId){
 const id=Number(chainId);
 if(id===8453)return "Base Mainnet";
 if(id===84532)return "Base Sepolia";
 return id?"Base "+id:"Base";
}

function showStatus(title,message,actions=[],kicker="AGENTPAY COMPANION"){
 $("#status-kicker").textContent=kicker;
 $("#status-title").textContent=title;
 $("#status-message").textContent=message;
 const box=$("#status-actions");box.innerHTML="";
 for(const action of actions){
  const b=document.createElement("button");b.type="button";b.textContent=action.label;
  if(action.primary)b.classList.add("primary-action");
  b.onclick=async()=>{ $("#status-dialog").close(); await action.onClick?.(); };
  box.appendChild(b);
 }
 $("#status-dialog").showModal();
}

function drawStages(upto=-1,denied=-1){
 const host=$("#stage-state");host.innerHTML="";
 for(let i=0;i<=upto;i++){
  const span=document.createElement("span");
  if(i===denied)span.className="denied";
  host.appendChild(span);
 }
}

async function getJson(path){
 const r=await fetch(path,{headers:{"accept":"application/json"}});
 const d=await r.json();
 if(!r.ok){const e=new Error(d.error||"request failed");e.status=r.status;e.payload=d;throw e}
 return d;
}

async function postJson(path,payload){
 const r=await fetch(path,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
 const d=await r.json();
 if(!r.ok){const e=new Error(d.error||"request failed");e.status=r.status;e.payload=d;throw e}
 return d;
}

function readActivity(){
 try{return JSON.parse(sessionStorage.getItem(SESSION_KEY)||"[]")}catch{return []}
}
function writeActivity(items){
 try{sessionStorage.setItem(SESSION_KEY,JSON.stringify(items.slice(0,5)))}catch{}
}
function renderActivity(){
 const list=$("#activity-list");
 const items=readActivity();
 list.innerHTML="";
 const rows=items.length?items:[{name:"Ready",status:"Waiting",amount:"—",kind:"info",time:"now"}];
 for(const item of rows.slice(0,5)){
  const row=document.createElement("p");
  row.innerHTML='<i class="'+esc(item.kind||"info")+'"></i><b>'+esc(item.name)+'</b><em>'+esc(item.status)+'</em><span>'+esc(item.amount||"—")+'</span><small>'+esc(item.time||"now")+'</small>';
  list.appendChild(row);
 }
 for(let i=rows.length;i<5;i++){
  const row=document.createElement("p");row.className="empty";
  row.innerHTML="<i></i><b>—</b><em>—</em><span>—</span><small>—</small>";
  list.appendChild(row);
 }
}
function addActivity(name,status,amount="—",kind="info"){
 const items=readActivity();
 items.unshift({name,status,amount,kind,time:"now"});
 writeActivity(items);
 renderActivity();
}

async function connectWallet(){
 if(!window.ethereum){
  showStatus("Wallet not detected","This browser is not exposing an EVM wallet. Enable MetaMask, Coinbase Wallet, or another Base-compatible injected wallet, then refresh.",[]);
  return null;
 }
 try{
  const accounts=await ethereum.request({method:"eth_requestAccounts"});
  connectedAccount=accounts?.[0]||null;
  $("#wallet-state").textContent=connectedAccount?short(connectedAccount,12):"Not connected";
  $("#runtime-state").textContent=connectedAccount?"Wallet ready":"Online";
  return connectedAccount;
 }catch(e){
  showStatus("Wallet connection stopped",e?.code===4001?"You rejected the wallet connection request.":(e?.message||"Wallet connection failed."));
  return null;
 }
}

async function ensureBase(chainIdHex){
 const id=parseInt(chainIdHex,16);
 const add={
  8453:{chainName:"Base",rpcUrls:["https://mainnet.base.org"],blockExplorerUrls:["https://basescan.org"]},
  84532:{chainName:"Base Sepolia",rpcUrls:["https://sepolia.base.org"],blockExplorerUrls:["https://sepolia.basescan.org"]}
 }[id];
 try{
  await ethereum.request({method:"wallet_switchEthereumChain",params:[{chainId:chainIdHex}]});
 }catch(e){
  if(e?.code!==4902||!add)throw e;
  await ethereum.request({method:"wallet_addEthereumChain",params:[{chainId:chainIdHex,nativeCurrency:{name:"Ether",symbol:"ETH",decimals:18},...add}]});
 }
}

function serviceBySlug(slug){
 return catalog.find(s=>s.slug===slug)||null;
}
function openService(slug="code"){
 const service=serviceBySlug(slug);
 if(!service){
  showStatus("Service unavailable","The service catalog has not loaded yet.");
  return;
 }
 currentService=service;
 $("#service-kicker").textContent="GOVERNED SERVICE · "+service.service_id;
 $("#service-title").textContent=service.title;
 $("#service-description").textContent=service.description;
 $("#service-price").textContent=usdc(service.price_atomic);
 $("#service-input-label").textContent=service.input_label||"Request";
 $("#service-input").placeholder=service.input_placeholder||"Enter the bounded service request…";
 $("#service-input").value="";
 $("#service-note").textContent="AgentPay binds this exact request to "+service.title+", "+usdc(service.price_atomic)+", the configured recipient, USDC and Base before the wallet sees a transaction.";
 $("#service-dialog").showModal();
 setTimeout(()=>$("#service-input").focus(),0);
}

async function reconcile(decisionId,txHash,sender){
 for(let attempt=0;attempt<30;attempt++){
  try{return await postJson("/api/live/reconcile",{decision_id:decisionId,transaction_hash:txHash,sender})}
  catch(e){
   if(e.status===409&&e.payload?.error==="settlement-not-observed"){
    $("#runtime-state").textContent="Reconciling";
    await new Promise(r=>setTimeout(r,2000));
    continue;
   }
   throw e;
  }
 }
 throw new Error("settlement-reconciliation-timeout");
}

async function runService(service,document){
 if(inProgress)return;
 if(!liveConfig.enabled){
  showStatus("Live mode unavailable","The site is not configured for live Base settlement. No wallet request was created.");
  return;
 }
 if(!document.trim()){
  showStatus("Request required","Enter the bounded input that this service should execute.");
  return;
 }
 const sender=connectedAccount||await connectWallet();
 if(!sender)return;

 inProgress=true;
 $("#runtime-state").textContent="Preparing";
 let prepared;
 try{
  drawStages(1);
  addActivity(service.title,"Quote prepared",usdc(service.price_atomic),"info");
  prepared=await postJson("/api/live/prepare",{
   service_id:service.service_id,
   amount_atomic:service.price_atomic,
   document
  });
  if(prepared.status==="DENIED"){
   currentProof=prepared.proof;currentArtifact=null;
   drawStages(2,2);
   addActivity(service.title,"Denied","—","bad");
   showStatus("Payment denied","Frequency denied this request before settlement. The proof records the failed authority constraint.",[
    {label:"Open Denial Proof",primary:true,onClick:openProof}
   ],"BOUNDED AUTHORITY");
   return;
  }

  drawStages(2);
  await ensureBase(prepared.wallet_request.chainId);
  $("#runtime-state").textContent="Wallet approval";
  addActivity(service.title,"Awaiting wallet",usdc(service.price_atomic),"info");

  let txHash;
  try{
   txHash=await ethereum.request({method:"eth_sendTransaction",params:[{
    from:sender,
    to:prepared.wallet_request.to,
    value:prepared.wallet_request.value,
    data:prepared.wallet_request.data
   }]});
  }catch(e){
   if(e?.code===4001){
    await postJson("/api/live/abort",{decision_id:prepared.decision_id}).catch(()=>{});
    addActivity(service.title,"Wallet rejected","—","bad");
   }else{
    await postJson("/api/live/uncertain",{decision_id:prepared.decision_id}).catch(()=>{});
    addActivity(service.title,"In doubt","—","info");
   }
   throw e;
  }

  drawStages(3);
  addActivity(service.title,"Broadcast",usdc(service.price_atomic),"info");
  const result=await reconcile(prepared.decision_id,txHash,sender);
  currentProof=result.proof;
  currentArtifact=result.artifact;
  for(let i=4;i<7;i++){drawStages(i);await new Promise(r=>setTimeout(r,120))}
  addActivity(service.title,"Verified",usdc(service.price_atomic),"info");
  $("#runtime-state").textContent="Verified";
  showStatus("Verified service purchase",service.title+" completed. Settlement, execution and independent observation are bound into a portable proof.",[
   {label:"Open Proof",primary:true,onClick:openProof},
   {label:"Run Another",onClick:()=>openService(service.slug)}
  ],"VERIFIED");
 }catch(e){
  console.error(e);
  $("#runtime-state").textContent="Attention";
  const message=e?.code===4001?"You rejected the wallet request. No payment was sent.":(e?.message||"Live payment failed.");
  showStatus("Live payment stopped",message,[
   {label:"Try Again",onClick:()=>openService(service.slug)}
  ]);
 }finally{
  inProgress=false;
 }
}

function downloadBlob(filename,type,content){
 const blob=new Blob([content],{type});
 const url=URL.createObjectURL(blob);
 const a=document.createElement("a");a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),0);
}

function openProof(){
 if(!currentProof){
  showStatus("No proof yet","Run a service first. A verified or denied proof will appear here.");
  return;
 }
 const p=currentProof;
 const rows=[
  ["Intent",p.intent?.intent_id],
  ["Quote",p.quote?.quote_id],
  ["Authority",p.authority?.decision],
  ["Settlement",p.settlement?.transaction_hash],
  ["Execution",p.result?.result_digest],
  ["Observation",p.observation?.observer_id],
  ["Proof",p.proof_hash]
 ];
 $("#evidence-grid").innerHTML=rows.filter(x=>x[1]).map(x=>'<article><small>'+esc(x[0])+'</small><div>'+esc(short(x[1],28))+'</div></article>').join("");
 $("#evidence-json").textContent=JSON.stringify(p,null,2);
 $("#artifact-download").hidden=!currentArtifact;
 $("#evidence-dialog").showModal();
}

function openCompanion(){
 const actions=[];
 let message="";
 if(inProgress){
  message="A governed payment is in progress. Companion is preserving the current state and will not start a second payment.";
 }else if(!liveConfig.enabled){
  message="Live settlement is not configured. Companion is keeping the interface read-only for payment execution.";
 }else if(!window.ethereum){
  message="Base is reachable, but this browser has no injected wallet. Enable a compatible wallet to run a real service.";
 }else if(!connectedAccount){
  message="Base is ready. Connect your wallet, then choose a bounded service request.";
  actions.push({label:"Connect Wallet",primary:true,onClick:connectWallet});
 }else if(currentProof){
  message="Wallet and Base are ready. The latest proof is available, or you can run another bounded service.";
  actions.push({label:"Open Proof",primary:true,onClick:openProof});
  actions.push({label:"Run Service",onClick:()=>openService("code")});
 }else{
  message="Wallet and Base are ready. Choose a service; AgentPay will bind the exact request and price before requesting wallet approval.";
  actions.push({label:"Run Code Analysis",primary:true,onClick:()=>openService("code")});
  actions.push({label:"Explore Services",onClick:focusServices});
 }
 showStatus("Companion",message,actions);
}

function focusServices(){
 const el=$(".service");
 el?.focus();
 $$(".service").forEach(card=>card.animate(
  [{boxShadow:"0 0 0 rgba(38,201,255,0)"},{boxShadow:"0 0 24px rgba(38,201,255,.35)"},{boxShadow:"0 0 0 rgba(38,201,255,0)"}],
  {duration:900}
 ));
}

async function refreshNetwork(){
 try{
  const d=await getJson("/api/live/network");
  $("#network-block").textContent=String(d.block);
  $("#network-gas").textContent=String(d.gas_gwei)+" gwei";
  $("#network-rpc").textContent=String(d.rpc_ms)+" ms";
  const label=chainName(d.chain_id);
  $("#network-label").textContent=label;
  $("#runtime-network").textContent=label;
  if(!connectedAccount&&!inProgress)$("#runtime-state").textContent="Online";
 }catch{
  if(!inProgress)$("#runtime-state").textContent="RPC offline";
 }
}

async function loadCatalog(){
 const d=await getJson("/api/catalog");
 catalog=Array.isArray(d.services)?d.services:[];
 for(const service of catalog){
  const price=$('[data-price="'+service.slug+'"]');
  if(price)price.textContent=usdc(service.price_atomic);
 }
}

async function init(){
 renderActivity();
 try{await loadCatalog()}catch(e){console.error(e);showStatus("Catalog unavailable","The service catalog could not be loaded. Payment controls remain unavailable.");}
 try{
  const d=await getJson("/api/live/config");liveConfig=d;
  const label=d.enabled?chainName(d.chain_id):"Demo";
  $("#network-label").textContent=label;$("#runtime-network").textContent=label;
  if(d.enabled)refreshNetwork();
 }catch{
  $("#runtime-state").textContent="Unavailable";
 }
 if(window.ethereum){
  const accounts=await ethereum.request({method:"eth_accounts"}).catch(()=>[]);
  connectedAccount=accounts?.[0]||null;
  $("#wallet-state").textContent=connectedAccount?short(connectedAccount,12):"Not connected";
  ethereum.on?.("accountsChanged",accounts=>{
   connectedAccount=accounts?.[0]||null;
   $("#wallet-state").textContent=connectedAccount?short(connectedAccount,12):"Not connected";
  });
  ethereum.on?.("chainChanged",()=>refreshNetwork());
 }
}

$("#run-service").onclick=()=>openService("code");
$("#nav-run").onclick=()=>openService("code");
$("#network-control").onclick=()=>connectWallet();
$("#nav-proofs").onclick=()=>openProof();
$("#explore").onclick=focusServices;
$("#search-control").onclick=focusServices;
$("#theme-control").onclick=()=>document.body.classList.toggle("dim");
$("#menu-control").onclick=openCompanion;
$("#service-cancel").onclick=()=>$("#service-dialog").close();
$("#service-submit").onclick=async()=>{
 const service=currentService;
 const document=$("#service-input").value;
 $("#service-dialog").close();
 if(service)await runService(service,document);
};
$("#proof-download").onclick=()=>{
 if(currentProof)downloadBlob("agentpay-proof.json","application/json",JSON.stringify(currentProof,null,2));
};
$("#artifact-download").onclick=()=>{
 if(!currentArtifact)return;
 if(currentArtifact.format==="obj"&&currentArtifact.obj){
  downloadBlob(currentArtifact.filename||"agentpay-artifact.obj","text/plain",currentArtifact.obj);
 }else{
  downloadBlob("agentpay-artifact.json","application/json",JSON.stringify(currentArtifact,null,2));
 }
};
$$(".svc").forEach(b=>b.onclick=()=>openService(b.dataset.service));

init();
setInterval(refreshNetwork,30000);
