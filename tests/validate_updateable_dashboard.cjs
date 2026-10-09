// Exercise the delivered HTML, imports, filters and serialization without a browser.
const fs=require('fs'),assert=require('assert/strict'),path=require('path');
const {JSDOM,VirtualConsole}=require(process.env.FAPESP_JSDOM||'jsdom');
const filename=process.argv[2],html=fs.readFileSync(filename,'utf8');
const originalPayload=JSON.parse(html.match(/<script id="payload" type="application\/json">([\s\S]*?)<\/script>/)[1]);
function environment(source){
 const scripts=[...source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script\s*>/g)].map(m=>m[1]);
 const vc=new VirtualConsole(),errors=[],graphs={},blobs=[];vc.on('jsdomError',e=>{if(!/navigation/.test(e.message))errors.push(e.message)});vc.on('error',e=>errors.push(String(e)));
 const dom=new JSDOM(source,{runScripts:'outside-only',url:'https://dashboard.invalid/',pretendToBeVisual:true,virtualConsole:vc});
 const w=dom.window,$=id=>w.document.getElementById(id),registered=[];
 Object.defineProperty(w.document,'modelContext',{value:{registerTool:tool=>registered.push(tool)}});
 w.URL.createObjectURL=b=>{blobs.push(b);return 'blob:validation'};w.URL.revokeObjectURL=()=>{};w.HTMLAnchorElement.prototype.click=function(){};
 w.Plotly={react:async(id,data,layout,config)=>{graphs[id]={data,layout,config};const el=$(id);el.data=data;el.layout=layout;el.removeAllListeners=()=>{};el.on=(event,fn)=>{el.callbacks=el.callbacks||{};el.callbacks[event]=fn;};},downloadImage:async()=>{}};
 w.eval(scripts.at(-1));
 return {dom,w,$,graphs,errors,blobs,registered};
}
const E=environment(html),{w,$,graphs}=E;
async function idle(){for(let i=0;i<300;i++){if($('busy').textContent==='Atualizado')return;if($('busy').textContent.startsWith('Erro'))throw Error($('busy').textContent);await new Promise(r=>setTimeout(r,10));}throw Error('Render did not complete');}
const sum=a=>a.reduce((s,n)=>s+n,0);
async function main(){
 await idle();const F=w.FAPESP,data=F.getData();
 assert.equal(E.registered.length,1);const readSelection=E.registered[0];assert.equal(readSelection.name,'fapesp_read_selection');assert.equal(readSelection.annotations.readOnlyHint,true);assert.equal(readSelection.inputSchema.additionalProperties,false);assert.equal(readSelection.execute({}).records,w.curadoriaView.length);assert.throws(()=>readSelection.execute({scope:'Mercosul'}),/objeto vazio/);
 assert.equal(Object.keys(graphs).length,17,'17 charts');assert(!/<script[^>]+src=|<link[^>]+href=["'](?!data:)/i.test(html),'fully embedded plotting library and favicon');
 assert(data.documents.filter(r=>r.source_id==='dataprivacy'&&r.date_precision==='day').length>=517,'Data Privacy has dated posts');
 assert.equal(sum(w.fapespAnalytics.intersection.map(x=>x.n)),w.fapespAnalytics.news.length,'exclusive intersection partitions dated publications');
 assert.equal(sum(graphs['chart-sources'].data[0].x),w.fapespAnalytics.news.length,'source plot preserves denominator');
 assert.equal(w.fapespAnalytics.concentration.at(-1).cumulative,100,'cumulative share 100%');
 assert.equal(data.documents.length,originalPayload.documents.length,'historical and curated URLs preserved');
 if(process.env.FAPESP_EXPECT_NEWS)assert.equal(w.fapespAnalytics.news.length,Number(process.env.FAPESP_EXPECT_NEWS),'expected eligible publication count');
 assert.equal(data.documents.filter(r=>r.manually_selected).length,originalPayload.documents.filter(r=>r.manually_selected).length,'catalog preserved');
 assert(data.documents.filter(r=>r.manually_selected).every(F.publisherReady),'catalog publisher and geography resolved');
 assert(data.documents.filter(r=>r.manually_selected).every(r=>r.catalog_credit),'original catalog credits retained');
 for(const id of ['chart-countries','chart-scopes','chart-intersection']){const trace=graphs[id].data[0];assert.equal(trace.type,'pie');assert.equal(sum(trace.values),w.fapespAnalytics.news.length,'pie partitions its stated denominator');assert(trace.customdata.every(d=>d[1]===w.fapespAnalytics.news.length));assert.equal(graphs[id].layout.legend.itemclick,false,'pie percentages do not silently renormalize on hidden slices');}
 const scopePie=graphs['chart-scopes'].data[0];for(let i=0;i<scopePie.values.length;i++)assert.equal(scopePie.marker.colors[i],F.color(scopePie.customdata[i][2]),'fixed scope colors in pie');
 assert(graphs['chart-intersection'].data[0].customdata.some(d=>d[2]==='Nenhuma menção a IA ou PD'),'absence of lexical mention labeled precisely');
 assert.equal(graphs['chart-comparison'].data[0].type,'scatter');assert.equal(graphs['chart-comparison'].layout.shapes.length,6,'four shaded quadrants and two median lines');
 assert.equal(graphs['chart-comparison'].layout.xaxis.type,'log','volume log scale is explicit and supports different group sizes');
 assert.equal(F.repairEncoding('ProteÃ§Ã£o de dados e usuÃ¡rios'),'Proteção de dados e usuários');assert.equal(F.repairEncoding('Proteção de dados e usuários'),'Proteção de dados e usuários','valid Unicode preserved');assert.equal(F.repairEncoding('â€œIAâ€\u009d'),'“IA”');
 if(originalPayload.documents.some(r=>r.original_title))assert(data.documents.some(r=>r.original_title&&r.title!==r.original_title),'raw title retained after encoding correction');
 assert.equal(graphs['chart-regions'].layout.shapes.length,6);assert(graphs['chart-regions'].data.every(t=>t.marker.color===F.color(t.customdata[0][0])),'scope colors match quadrant points');
 for(const id of Object.keys(graphs)){assert(graphs[id].layout.annotations.some(a=>a.text.startsWith('Fonte: elaboração própria')),'source inside every exported figure');assert($(id).dataset.academicCaption.includes('Unidade: URL canônica única'),'complete academic caption');}
 assert.equal(w.document.querySelectorAll('.figure-source').length,17);assert(!$('publisher-provenance').textContent.includes('Não informada'));
 const emptyPublisher=F.normalizeRecord({title:'Teste de privacidade',url:'https://www.dataprivacybr.org/provenance-test',date:'2026-10-06',source:'Não informada'});assert.equal(emptyPublisher.source,'Data Privacy Brasil');assert(F.publisherReady(emptyPublisher),'publisher recovered from known domain');
 const legacyPublisher=F.normalizeRecord({title:'Teste da fonte legada',url:'https://www.dataprivacybr.org/legacy-provenance-test',date:'2026-10-06',source_id:'data_privacy_colab'});assert.equal(legacyPublisher.source,'Data Privacy Brasil','unregistered legacy source ID recovered from known publisher domain');
 const preprint=F.normalizeRecord({title:'Pesquisa IA',url:'https://arxiv.org/abs/2601.00000',date:'2026-01-01',source:'Autoria de teste',manually_selected:true});assert.equal(preprint.source,'arXiv · repositório de preprints');assert.equal(preprint.catalog_credit,'Autoria de teste');assert.equal(preprint.region,'Global');
 const unspecifiedAgency=F.normalizeRecord({title:'Agência não identificada',url:'https://www.gov.br/outra-agencia/noticia',date:'2026-10-06'});assert(!F.publisherReady(unspecifiedAgency),'shared government domain does not invent an agency');
 const spoof=F.normalizeRecord({title:'Fonte incompatível',url:'https://example.org/article',date:'2026-10-06',source_id:'anpd'});assert(!F.publisherReady(spoof),'registered publisher cannot be attached to another domain');
 const fixture=[...Array.from({length:10},(_,i)=>({source:'A',keywords:i<5?['Privacidade']:[]})),...Array.from({length:20},(_,i)=>({source:'B',keywords:i<4?['Privacidade']:[]}))],model=F.quadrantModel(fixture,'source',['A','B'],true,1,'data');assert.equal(model.xcut,15);assert.equal(model.ycut,35);assert.deepEqual(Array.from(model.points.map(p=>[p.name,p.n,p.x,p.y]).flat()),['A',10,10,50,'B',20,20,20],'quadrant coordinates and median calculations');
 const eligibleBefore=w.fapespAnalytics.news.length;F.mergeRecords([unspecifiedAgency]);await idle();assert.equal(w.fapespAnalytics.news.length,eligibleBefore,'incomplete publisher excluded from analyses');assert(w.fapespAnalytics.pending.some(r=>r.url===unspecifiedAgency.url),'incomplete record remains in audit');
 const mercosul=F.color('Mercosul');assert.equal(mercosul,F.color('mercosur'));assert.notEqual(mercosul,F.color('UE'));
 await F.setFilter('region',['UE']);await idle();assert(w.curadoriaView.every(r=>r.region==='UE'));assert.equal(F.color('Mercosul'),mercosul,'colors do not change when filtered');
 assert(graphs['chart-months'].data.every(t=>t.name==='UE'),'monthly scope traces honor global filter');
 await F.setFilter('region',[]);await idle();assert.equal(w.curadoriaView.length,0,'none means zero, not all');assert.equal(w.fapespAnalytics.news.length,0);
 F.reset();await idle();$('series-none').click();await idle();assert.equal(graphs['chart-comparison'].data.length,0,'all comparison series removable');$('series-all').click();await idle();
 const piePoint=graphs['chart-scopes'].data[0].customdata.find(d=>d[2]==='UE');$('chart-scopes').callbacks.plotly_click({points:[{customdata:piePoint}]});await idle();assert(w.curadoriaView.every(r=>r.region==='UE'),'pie click filters all charts');F.reset();await idle();
 const sourceBox=[...$('comparison-series').querySelectorAll('input')].find(b=>b.value==='Data Privacy Brasil');const beforeQuadrants=w.fapespAnalytics.comparisonQuadrants.points.length;sourceBox.checked=false;sourceBox.dispatchEvent(new w.Event('change'));await idle();assert.equal(w.fapespAnalytics.comparisonQuadrants.points.length,beforeQuadrants-1,'quadrant groups removable');assert(!w.fapespAnalytics.comparisonQuadrants.points.some(p=>p.name==='Data Privacy Brasil'));$('series-all').click();await idle();
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
 assert(exported.some(r=>r.grafico==='Quadrantes · IA × PD por âmbito'&&r.mediana_x!==''&&r.n_pd!==''),'quadrant values and reference lines exported');assert(exported.every(r=>r.fonte_dados.includes('Elaboração própria')),'source attribution in analytical CSV');
 $('compare-view').value='quadrants';$('compare-view').dispatchEvent(new w.Event('change'));$('quadrant-theme').value='ai';$('quadrant-theme').dispatchEvent(new w.Event('change'));await idle();const quadrantSaved=environment(F.serializeHTML());for(let i=0;i<300&&quadrantSaved.$('busy').textContent!=='Atualizado';i++)await new Promise(r=>setTimeout(r,10));assert.equal(quadrantSaved.$('quadrant-theme').value,'ai');assert.equal(quadrantSaved.$('compare-view').value,'quadrants');quadrantSaved.dom.window.close();
 $('audit-scope').value='all';$('audit-scope').dispatchEvent(new w.Event('change'));await idle();assert.equal(w.fapespAnalytics.audit.length,F.getData().documents.length,'explicit full-base audit');
 before=F.getData().documents.length;w.fetch=async()=>{throw Error('offline')};await $('sync-github').onclick();assert.equal(F.getData().documents.length,before,'failed GitHub fetch preserves base');assert($('update-message').classList.contains('error'),'network error visible');
 const maliciousTitle=F.normalizeRecord({title:'</script><script>alert(1)</script> IA',url:'https://www.dataprivacybr.org/security-test',date:'2026-10-06'});F.mergeRecords([maliciousTitle]);await idle();const safe=F.serializeHTML();assert(!safe.includes('</script><script>alert(1)</script>'),'embedded payload cannot escape script');
 assert.equal(E.errors.length,0,E.errors.join('; '));
 console.log('PASS: 17 charts; three pie/donut partitions; two quadrant models and medians; publisher provenance and strict exclusions; preserved history/catalog/credits; pie-linked filters; include/exclude; fixed colors; academic captions/CSV; CSV/JSON imports; saved HTML restores data and controls; safe links; offline error preservation.');
}
main().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>E.dom.window.close());
