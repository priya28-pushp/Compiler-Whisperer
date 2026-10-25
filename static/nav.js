// Shared top bar + login guard for every signed-in page.
(async()=>{
  const r=await fetch('/api/me');
  if(r.status===401){location.href='/login';return;}
  const me=await r.json();window.me=me;
  const links=[['/','Analyzer'],['/lab','Compiler Lab'],['/dashboard','Dashboard']];
  const nav=document.createElement('nav');nav.className='nav';
  nav.innerHTML=`<a class="brand" href="/">Compiler <i>Whisperer</i></a>`+
    links.map(([h,t])=>`<a class="l ${location.pathname===h?'on':''}" href="${h}">${t}</a>`).join('')+
    `<span style="flex:1"></span><span class="who">Hi, ${me.name.replace(/[<>&]/g,'')}</span><button class="ghost" id="out-btn">Log out</button>`;
  document.querySelector('.wrap').prepend(nav);
  document.getElementById('out-btn').onclick=async()=>{await fetch('/api/logout',{method:'POST'});location.href='/login';};
})();
