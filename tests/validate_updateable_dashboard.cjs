// Exercise the delivered HTML, imports, filters and serialization without a browser.
const fs=require('fs'),assert=require('assert/strict'),path=require('path');
const {JSDOM,VirtualConsole}=require(process.env.FAPESP_JSDOM||'jsdom');
const filename=process.argv[2],html=fs.readFileSync(filename,'utf8');
function environment(source){
 const scripts=[...source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script\s*>/g)].map(m=>m[1]);
 const vc=new VirtualConsole(),errors=[],graphs={},blobs=[];vc.on('jsdomError',e=>{if(!/navigation/.test(e.message))errors.push(e.message)});vc.on('error',e=>errors.push(String(e)));
 const dom=new JSDOM(source,{runScripts:'outside-only',url:'https://dashboard.invalid/',pretendToBeVisual:true,virtualConsole:vc});
 const w=dom.window,$=id=>w.document.getElementById(id);
 w.URL.createObjectURL=b=>{blobs.push(b);return 'blob:validation'};w.URL.revokeObjectURL=()=>{};w.HTMLAnchorElement.prototype.click=function(){};
 w.Plotly={react:async(id,data,layout,config)=>{graphs[id]={data,layout,config};const el=$(id);el.data=data;el.layout=layout;el.removeAllListeners=()=>{};el.on=(event,fn)=>{el.callbacks=el.callbacks||{};el.callbacks[event]=fn;};},downloadImage:async()=>{}};
 w.eval(scripts.at(-1));
 return {dom,w,$,graphs,errors,blobs};
}
const E=environment(html),{w,$,graphs}=E;
async function idle(){for(let i=0;i<300;i++){if($('busy').textContent==='Atualizado')return;if($('busy').textContent.startsWith('Erro'))throw Error($('busy').textContent);await new Promise(r=>setTimeout(r,10));}throw Error('Render did not complete');}
const sum=a=>a.reduce((s,n)=>s+n,0);
async function main(){
 await idle();const F=w.FAPESP,data=F.getData();
 assert.equal(Object.keys(graphs).length,17,'17 charts');assert(!/<script[^>]+src=|<link[^>]+href=/i.test(html),'fully embedded plotting library');
 assert(data.documents.filter(r=>r.source_id==='dataprivacy'&&r.date_precision==='day').length>=517,'Data Privacy has dated posts');
 assert.equal(sum(w.fapespAnalytics.intersection.map(x=>x.n)),w.fapespAnalytics.news.length,'exclusive intersection partitions dated publications');
 assert.equal(sum(graphs['chart-sources'].data[0].x),w.fapespAnalytics.news.length,'source plot preserves denominator');
 assert.equal(w.fapespAnalytics.concentration.at(-1).cumulative,100,'cumulative share 100%');
 const mercosul=F.color('Mercosul');assert.equal(mercosul,F.color('mercosur'));assert.notEqual(mercosul,F.color('UE'));
 await F.setFilter('region',['UE']);await idle();assert(w.curadoriaView.every(r=>r.region==='UE'));assert.equal(F.color('Mercosul'),mercosul,'colors do not change when filtered');
 assert(graphs['chart-months'].data.every(t=>t.name==='UE'),'monthly scope traces honor global filter');
 await F.setFilter('region',[]);await idle();assert.equal(w.curadoriaView.length,0,'none means zero, not all');assert.equal(w.fapespAnalytics.news.length,0);
 F.reset();await idle();$('series-none').click();await idle();assert.equal(graphs['chart-comparison'].data.length,0,'all comparison series removable');$('series-all').click();await idle();
 const rows=F.parseCSV('\uFEFFTítulo;Link;Data;Resumo\r\n"Teste; com aspas ""duplas""";https://www.dataprivacybr.org/teste/;06/10/2026;"resumo\nmultilinha"');
 assert.equal(rows.length,1);assert.equal(rows[0].Título,'Teste; com aspas "duplas"');assert.equal(rows[0].Resumo,'resumo\nmultilinha');
 assert.throws(()=>F.parseCSV('title,url\n"sem fechar,https://x.org'),/aspas/);
 assert.deepEqual(Array.from(F.parseDate('2026-10-06T15:00:00')),['2026-10-06','day']);assert.deepEqual(Array.from(F.parseDate('31/02/2026')),['','unknown']);
 const imported=F.normalizeRecord(rows[0],'publicacoes_data_privacy_brasil.csv');assert.equal(imported.source_id,'dataprivacy');assert.equal(imported.country,'Brasil');assert.equal(imported.region,'Mercosul');
 const malicious=F.normalizeRecord({title:'<img src=x onerror=alert(1)> Proteção de dados',url:'javascript:alert(1)'});assert.equal(malicious,null,'unsafe links rejected');
 let before=F.getData().documents.length;const stats=F.mergeRecords([imported]);await idle();assert.equal(stats.added,1);assert.equal(F.getData().documents.length,before+1);
 F.mergeRecords([imported]);await idle();assert.equal(F.getData().documents.length,before+1,'duplicate URL counts once');
 const invalidBefore=F.getData().documents.length;assert.throws(()=>F.mergeRecords([]),/preservada/);assert.equal(F.getData().documents.length,invalidBefore,'invalid import preserves data');
 await F.setFilter('source',['Data Privacy Brasil']);await idle();assert(w.curadoriaView.every(r=>r.source==='Data Privacy Brasil'),'source filter');assert(w.fapespAnalytics.news.length>=517,'all dated Data Privacy accessible');
 $('compare-view').value='time';$('compare-view').dispatchEvent(new w.Event('change'));await idle();assert(graphs['chart-comparison'].data.every(t=>t.type==='scatter'));
 $('analysis-text').value='title_summary';$('analysis-text').dispatchEvent(new w.Event('change'));await idle();assert(F.getData().documents.every(r=>r.analysis_text.startsWith(r.title)));
 const saved=F.serializeHTML();assert(saved.includes('Teste; com aspas'));assert(!saved.includes('__DASHBOARD_JS__'));
 const restored=environment(saved);for(let i=0;i<300&&restored.$('busy').textContent!=='Atualizado';i++)await new Promise(r=>setTimeout(r,10));
 assert.equal(restored.w.FAPESP.getData().documents.length,F.getData().documents.length,'updated data embedded into saved HTML');assert.deepEqual(Array.from(restored.w.FAPESP.getFilters().source),['Data Privacy Brasil'],'filters survive saved HTML');assert.equal(restored.$('analysis-text').value,'title_summary');assert.equal(restored.w.FAPESP.color('Mercosul'),mercosul);restored.dom.window.close();
 const exported=F.parseCSV(F.analyticalCSV());assert(exported.length>20);assert(exported.every(r=>r.denominador!==undefined),'analytical exports include denominators');
 $('audit-scope').value='all';$('audit-scope').dispatchEvent(new w.Event('change'));await idle();assert.equal(w.fapespAnalytics.audit.length,F.getData().documents.length,'explicit full-base audit');
 before=F.getData().documents.length;w.fetch=async()=>{throw Error('offline')};await $('sync-github').onclick();assert.equal(F.getData().documents.length,before,'failed GitHub fetch preserves base');assert($('update-message').classList.contains('error'),'network error visible');
 const maliciousTitle=F.normalizeRecord({title:'</script><script>alert(1)</script> IA',url:'https://www.dataprivacybr.org/security-test',date:'2026-10-06'});F.mergeRecords([maliciousTitle]);await idle();const safe=F.serializeHTML();assert(!safe.includes('</script><script>alert(1)</script>'),'embedded payload cannot escape script');
 assert.equal(E.errors.length,0,E.errors.join('; '));
 console.log('PASS: 17 charts; dated Data Privacy; multiple filters; include/exclude; stable colors; CSV/JSON imports; deduplication; saved HTML restores data and filters; exports; safe links; offline error preservation.');
}
main().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>E.dom.window.close());
