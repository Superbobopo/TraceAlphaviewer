/* Affichage partage entre le rapport React et le secours HTML autonome. */
(function (scope) {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => value == null ? '—' : Number(value).toLocaleString('fr-FR', {minimumFractionDigits:1, maximumFractionDigits:1});
  const signed = value => value == null ? '—' : `${value > 0 ? '+' : ''}${number(value)}`;
  const severity = group => group.field_severity || group.severity;
  const severityLabel = group => ({error:'Critique',warning:'Alerte',info:'Info'}[severity(group)] || 'Info');
  const action = group => group.field_action || group.action || group.title;
  const colors = {length:'#A78BFA',width:'#14B8A6',height:'#FDE047'};
  const list = values => `<ul>${(values || []).map(value => `<li>${esc(value)}</li>`).join('')}</ul>`;
  const exclusionLabels = {orientation:'orientations différentes',invalid:'mesures invalides',incomplete:'mesures incomplètes',reference_absent:'références BdD absentes',ambiguous:'identités ambiguës',unknown:'UNKNOWN sans produit identifié',identity_unconfirmed:'identifications non confirmées',reference_conflict:'références contradictoires',t4c_absent:'longueur T4C absente'};
  function biasText(bias) {
    return bias ? `Décalage régulier autour de ${signed(bias.median)} mm : ${number(bias.percent)} %, ${bias.count} boîtes, ${bias.references} références. ${bias.advice}` : '';
  }
  function direction(name, value) {
    if (!value) return 'Sans biais moyen';
    const labels = {length:['trop court','trop long'],width:['trop étroit','trop large'],height:['trop bas','trop haut']};
    return `${number(Math.abs(value))} mm ${labels[name][value > 0 ? 1 : 0]}`;
  }
  function measurementHtml(summary, data, state) {
    const axes = ['length','width','height'].filter(name => summary?.axes?.[name]).map(name => [name,summary.axes[name]]);
    if (!axes.length) return '<p class="muted">Mesures indisponibles.</p>';
    const excluded = Object.entries(summary.excluded || {}).filter(([,n]) => n).map(([key,n]) => `${exclusionLabels[key] || key} : ${n}`).join(' · ');
    return `<p class="measurement-total">${esc(measurementTotal(summary))}</p><p class="muted">${esc(globalMeasurementText(summary))}</p><p class="muted">Une boîte compte une fois, avec sa dernière mesure complète. Écart = mesure − dimension attendue dans la base de données (BdD). Une mesure est bonne jusqu'à ±${summary.tolerance_mm} mm inclus.</p><div class="axis-grid">${axes.map(([name,axis]) => {
      const bad=axis.anomalies;
      return `<article class="axis" data-axis="${name}" style="--axis:${colors[name]}"><h3>${esc(axis.label)}</h3><p class="measure-counts">${esc(measurementCounts(axis))}</p><p class="muted">${axis.all.references} référence(s) comparables</p><p class="muted">Plage des mauvaises mesures</p><div class="metric">${range(bad)}</div><p>En moins : <strong>${extreme(bad.worst_under)}</strong><br>En trop : <strong>${extreme(bad.worst_over)}</strong></p><div class="actions"><button class="small" data-measure-axis="${name}" data-measure-side="under">${bad.under_count} trop petites</button><button class="small" data-measure-axis="${name}" data-measure-side="over">${bad.over_count} trop grandes</button></div><p>Décalage moyen : <strong>${signed(bad.mean_signed)}${bad.count?' mm':''}</strong><br>Erreur moyenne : <strong>${number(bad.mean_abs)}${bad.count?' mm':''}</strong></p><p class="muted">Moyennes des mauvaises mesures. Le décalage tient compte du signe ; l'erreur moyenne indique de combien la mesure se trompe, sans tenir compte du sens.</p>${axis.bias?`<p class="bias">${esc(biasText(axis.bias))}</p>`:''}${!axis.bias&&axis.interpretation?.length?`<div class="bias"><strong>Pistes à vérifier</strong>${list(axis.interpretation)}</div>`:''}<details class="measure-details"><summary>Chiffres complets et toutes les mesures</summary><div class="table-wrap"><table><thead><tr><th>Indicateur</th><th>Mauvaises</th><th>Toutes</th></tr></thead><tbody>${[['Boîtes','count'],['Références','references'],['Écart minimum (mm)','min_signed'],['Écart maximum (mm)','max_signed'],['Décalage moyen (mm)','mean_signed'],['Erreur moyenne (mm)','mean_abs'],['Erreur absolue minimum (mm)','min_abs'],['Erreur absolue maximum (mm)','max_abs']].map(([label,key]) => `<tr><td>${label}</td><td>${['count','references'].includes(key)?bad[key]:key.includes('signed')?signed(bad[key]):number(bad[key])}</td><td>${['count','references'].includes(key)?axis.all[key]:key.includes('signed')?signed(axis.all[key]):number(axis.all[key])}</td></tr>`).join('')}</tbody></table></div></details></article>`;
    }).join('')}</div>${data&&state?referenceHtml(data,state):''}${excluded?`<p class="muted">Exclus du bilan : ${esc(excluded)}. Ces boîtes ne sont comptées ni bonnes ni mauvaises.</p>`:''}`;
  }
  function referenceHtml(data,state) {
    const selected=state.measurementSelection;if(!selected)return '';
    const {axis,side,barcode,page}=selected;
    const rows=data.measurement_references?.[axis]?.[side] || [];
    const row=rows.find(item=>item.barcode===barcode);
    const items=barcode ? (row?.sample_ids || []).map(id=>state.measurementExamples.get(id)).filter(Boolean) : rows;
    const visible=items.slice(page*25,(page+1)*25);
    const title=`${data.measurements.axes[axis].label} · ${side==='under'?'Trop petites':'Trop grandes'}`;
    const table=`<div class="table-wrap"><table><thead><tr><th>Référence / produit</th><th>Boîtes</th><th>Plage</th><th>Pire écart</th></tr></thead><tbody>${visible.map(item=>`<tr><td><button class="small" data-measure-barcode="${esc(item.barcode)}">${esc(item.barcode)}</button><br>${esc(item.name)}</td><td>${item.count}/${item.total} (${number(item.percent)} %)</td><td>${range(item)}</td><td>${signed(item.worst)} mm</td></tr>`).join('')}</tbody></table></div>`;
    return `<section class="measurement-reference-list"><h3>${esc(title)}</h3><p class="muted">Produits identifiés et BdD vérifiée pour le même cycle. Tri : pire écart, puis nombre de boîtes concernées.</p>${barcode?`<h4>${esc(barcode)} · ${esc(row?.name)}</h4><button class="small" data-measure-back>Retour aux références</button>`:''}${!items.length?'<p>Aucune boîte pour ce côté.</p>':barcode?visible.map(sample=>sampleHtml(sample,state.connected,axis)).join(''):table}<div class="pagination"><button class="small" data-measure-page="${page-1}" ${page===0?'disabled':''}>Précédents</button><span>Page ${page+1}/${Math.max(1,Math.ceil(items.length/25))} · ${items.length} ${barcode?'boîtes':'références'}</span><button class="small" data-measure-page="${page+1}" ${(page+1)*25>=items.length?'disabled':''}>Suivants</button><button class="small" data-measure-close>Fermer la liste</button></div></section>`;
  }
  const range = stats => stats?.count ? `${signed(stats.min_signed)} à ${signed(stats.max_signed)} mm` : 'Aucune mauvaise mesure';
  const extreme = value => value == null ? 'Aucune' : `${signed(value)} mm`;
  const measurementCounts = axis => `Bonnes mesures : ${axis.all.within_count}/${axis.all.count} (${number(axis.all.within_percent)} %) · Mauvaises mesures : ${axis.all.outside_count}/${axis.all.count} (${number(axis.all.outside_percent)} %)`;
  const measurementTotal = summary => `${summary.cycle_count || 0} cycles de boîtes analysés sur T5 · ${summary.comparable_count || 0} comparables · ${summary.excluded_count || 0} exclus`;
  const globalMeasurementText = summary => summary.global ? `Toutes dimensions : ${summary.global.within_count}/${summary.global.count} boîtes conformes (${number(summary.global.within_percent)} %) · ${summary.global.outside_count}/${summary.global.count} hors tolérance (${number(summary.global.outside_percent)} %). Une boîte en erreur sur plusieurs dimensions compte une seule fois.` : '';
  function sampleHtml(sample, connected, axis='') {
    const line=sample.sources?.[axis] || sample.line;
    const measures = sample.measured ? `<div class="table-wrap"><table><thead><tr><th>Dimension</th><th>BdD</th><th>Mesure</th><th>Écart</th></tr></thead><tbody>${[['Longueur T4/C6',2],['Largeur T5/C9',0],['Hauteur T5/LzB',1]].map(([label,i]) => `<tr><td>${label}</td><td>${sample.expected[i]} mm</td><td>${sample.measured[i]} mm</td><td>${signed(sample.deltas[i])} mm</td></tr>`).join('')}</tbody></table></div>` : `<p>${esc(sample.detail)}</p>`;
    return `<article class="sample"><div class="sample-head"><strong>${esc(sample.time_str)} · L.${line}</strong><button class="small" data-navigate="${esc(sample.id)}" ${axis?`data-navigate-axis="${axis}"`:''} ${connected?'':'disabled'}>Voir dans AlphaViewer</button></div><p class="muted">${esc([sample.box,sample.barcode].filter(Boolean).join(' · '))}${sample.invalid?' · Mesure invalide, exclue du bilan':''}${sample.final===false?' · Mesure antérieure, hors effectif final':''}</p>${sample.rejected_dimensions?`<p>Produit identifié puis rejeté pour dimensions : ${esc(sample.current_reference)}</p>`:''}${measures}${sample.t4t?`<p class="muted">T4T (complément) : ${sample.t4t} mm ; diffT4 ${signed(sample.diff_t4)} mm.</p>`:''}${sample.sources?`<p class="muted">Sources : T4C L.${sample.sources.length} · C9 L.${sample.sources.width} · hauteur L.${sample.sources.height} · BdD L.${sample.sources.bdd} · identification L.${sample.sources.identity}.</p>`:''}<details><summary>Contexte de la trace</summary><pre>${esc((sample.context||[]).map(row => `L.${row.line}  ${row.text}`).join('\n') || 'Contexte indisponible.')}</pre></details></article>`;
  }
  function mount(root, data) {
    const groups = data.groups || [];
    const indexed = groups.map(group => ({group,search:JSON.stringify(group).toLocaleLowerCase('fr')}));
    const state = {search:'',family:'all',level:'all',pages:{},open:new Set(['measurements']),connected:false,message:''};
    state.measurementSelection=null;
    state.measurementExamples=new Map((data.measurement_examples || []).map(sample=>[sample.id,sample]));
    const local = location.protocol==='http:' && location.hostname==='127.0.0.1' && /\/view\.html$/.test(location.pathname);
    const controller = new AbortController();
    let disposed = false, debounce;
    function render() {
      root.querySelectorAll('details[data-open]').forEach(node => node.open ? state.open.add(node.dataset.open) : state.open.delete(node.dataset.open));
      const filtered = indexed.filter(({group,search}) => (state.family==='all'||group.family===state.family) && (state.level==='all'||severity(group)===state.level) && (!state.search||search.includes(state.search.toLocaleLowerCase('fr')))).map(x => x.group);
      const counts = data.counts || {};
      const source = data.source || {};
      root.innerHTML = `<main class="report"><header class="hero"><div><div class="eyebrow">TraceAlphaViewer · diagnostic terrain</div><h1>Comprendre cette trace</h1><p>${esc(source.name || 'Trace analysée')}</p><p class="muted">${esc(source.start)} → ${esc(source.end)} · ${esc(source.duration)} · Généré le ${esc(data.generated_at)}</p></div><div><div class="actions"><button class="primary" data-pdf>Exporter PDF</button></div><p class="status" role="status">${esc(state.message || (state.connected?'Liaison avec la trace ouverte dans AlphaViewer.':'Consultation autonome · navigation viewer indisponible.'))}</p></div></header><div class="summary-grid">${[['Problèmes critiques',counts.error || 0],['Alertes à vérifier',counts.warning || 0],['Boîtes analysées',counts.analyzed_boxes || 0],['Problèmes différents',counts.types || 0]].map(([label,value])=>`<div class="stat"><span class="muted">${label}</span><strong>${value}</strong></div>`).join('')}</div><section class="section"><h2>${esc(data.verdict?.title || 'Synthèse')}</h2><p>${esc(data.verdict?.text)}</p><p class="muted">${counts.incidents || 0} diagnostics regroupés · ${counts.info || 0} types informatifs. Cliquer sur un problème pour consulter ses chiffres, les contrôles et les exemples.</p><div class="actions">${(data.priority || []).slice(0,5).map(group=>`<button class="small" data-priority="${esc(group.id)}">${esc(group.title)} · ${esc(group.affected_label || group.metric)}<span class="priority-explanation">${esc(group.field_explanation || group.impact)}</span><span class="priority-action">Premier contrôle : ${esc(action(group))}</span></button>`).join('')}</div></section><details class="section" data-open="measurements" ${state.open.has('measurements')?'open':''}><summary>Bilan des mesures <span class="muted">${data.measurements?.comparable_count || 0} boîtes comparables · longueur, largeur, hauteur</span></summary>${measurementHtml(data.measurements,data,state)}</details>${cameraHtml(data.camera,state.open.has('camera'))}<div class="filters"><input type="search" aria-label="Rechercher un diagnostic" placeholder="Code, référence, boîte, problème…" value="${esc(state.search)}"><select aria-label="Niveau" data-level>${[['all','Tous les niveaux'],['error','Critiques'],['warning','Alertes'],['info','Informations']].map(([key,label])=>`<option value="${key}" ${state.level===key?'selected':''}>${label}</option>`).join('')}</select><select aria-label="Famille" data-family>${(data.families || []).filter(item=>item.id!=='critical').map(item=>`<option value="${item.id}" ${state.family===item.id?'selected':''}>${esc(item.label)}</option>`).join('')}</select></div><h2 id="problems">${filtered.length} type(s) de problème</h2>${filtered.map(group=>groupHtml(group,state)).join('') || '<div class="empty">Aucun diagnostic pour ces critères.</div>'}<details class="section" data-open="zones" ${state.open.has('zones')?'open':''}><summary>Répartition par zone</summary>${list((data.zones||[]).map(zone=>`${zone.label || zone.family} : ${zone.occurrences} occurrences, ${zone.errors} critiques, ${zone.warnings} alertes`))}</details><p class="footer">Les constats proviennent de la trace. Les causes proposées et les pistes de calibrage restent à confirmer sur la machine. Les exemples antérieurs sont conservés sans compter plusieurs fois la même boîte.</p></main>`;
    }
    function refreshStatus() {
      root.querySelectorAll('[data-navigate]').forEach(button => button.disabled=!state.connected);
      const label = root.querySelector('.status');
      if(label) label.textContent = state.message || (state.connected?'Liaison avec la trace ouverte dans AlphaViewer.':'La trace source est fermée ou la liaison est indisponible.');
    }
    async function status() {
      if(!local || disposed) return;
      try { const response=await fetch('status',{signal:controller.signal}); state.connected=response.ok && (await response.json()).connected; }
      catch { state.connected=false; }
      if(!disposed) refreshStatus();
    }
    async function click(event) {
      const button=event.target.closest('button'); if(!button) return;
      if(button.hasAttribute('data-pdf')) {downloadPdf(data);return;}
      if(button.dataset.measureAxis){state.measurementSelection={axis:button.dataset.measureAxis,side:button.dataset.measureSide,page:0,barcode:''};render();root.querySelector('.measurement-reference-list')?.scrollIntoView({block:'nearest'});return;}
      if(button.hasAttribute('data-measure-close')){state.measurementSelection=null;render();return;}
      if(button.hasAttribute('data-measure-back')){state.measurementSelection.barcode='';state.measurementSelection.page=0;render();return;}
      if(button.dataset.measureBarcode){state.measurementSelection.barcode=button.dataset.measureBarcode;state.measurementSelection.page=0;render();return;}
      if(button.hasAttribute('data-measure-page')){state.measurementSelection.page=Number(button.dataset.measurePage);render();return;}
      if(button.dataset.navigate) {
        button.disabled=true;state.message='Recherche de cet exemple dans AlphaViewer…';refreshStatus();
        try {const response=await fetch('navigate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sample_id:button.dataset.navigate,...(button.dataset.navigateAxis?{axis:button.dataset.navigateAxis}:{})}),signal:controller.signal});const result=await response.json();state.message=result.ok?`AlphaViewer positionné à la ligne ${result.line}.`:(result.error || 'Navigation indisponible.');}
        catch {state.message='La trace source est fermée ou remplacée. Rouvrir le rapport depuis la bonne trace.';state.connected=false;}
        if(!disposed) refreshStatus();return;
      }
      if(button.dataset.priority) {
        state.family='all';state.level='all';state.search='';render();
        const card=[...root.querySelectorAll('details[data-group]')].find(node=>node.dataset.group===button.dataset.priority);
        if(card){card.open=true;card.scrollIntoView({behavior:'smooth',block:'start'});}return;
      }
      if(button.dataset.pageGroup) {state.pages[button.dataset.pageGroup]=Number(button.dataset.page);render();}
    }
    function input(event) {
      if(event.target.matches('input[type=search]')) {
        state.search=event.target.value;clearTimeout(debounce);
        debounce=setTimeout(()=>{const pos=event.target.selectionStart;render();const field=root.querySelector('input[type=search]');field.focus();try{field.setSelectionRange(pos,pos);}catch{}},180);
      } else if(event.target.matches('[data-family],[data-level]')) {
        state[event.target.hasAttribute('data-family')?'family':'level']=event.target.value;render();
      }
    }
    root.addEventListener('click',click);root.addEventListener('input',input);
    render();status();const timer=setInterval(status,10000);
    return ()=>{disposed=true;controller.abort();clearTimeout(debounce);clearInterval(timer);root.removeEventListener('click',click);root.removeEventListener('input',input);};
  }
  function cameraHtml(camera, open=false) {
    if(!camera?.available)return '';
    const max=Math.max(1,...(camera.chart||[]).map(row=>row.success_count));
    return `<details class="section" data-open="camera" ${open?'open':''}><summary>Lecture des caméras <span class="muted">${esc(camera.note)}</span></summary>${(camera.chart||[]).map(row=>`<div class="camera-row"><span>${esc(row.label)}</span><div class="bar"><i class="${row.status==='zero'?'zero':''}" style="width:${100*row.success_count/max}%"></i></div><strong>${row.success_count} lectures</strong></div><p class="muted">${esc(row.label)} : ${esc(row.status_label)}</p>`).join('')}<div class="table-wrap"><table><thead><tr><th>Lecteur</th><th>Caméras attendues</th><th>Boîtes</th><th>Lectures à 0 code</th></tr></thead><tbody>${(camera.reader_stats||[]).map(row=>`<tr><td>${esc(row.reader)}</td><td>${esc(row.expected_cameras)}</td><td>${row.boxes}</td><td>${esc(row.zero_code_label)}</td></tr>`).join('')}</tbody></table></div></details>`;
  }
  function groupHtml(group,state) {
    const examples=group.examples||[],page=state.pages[group.id];
    const selected=page==null?examples.filter(s=>(group.representative_ids||[]).includes(s.id)):examples.slice(page*25,page*25+25);
    const pagination=examples.length>3?`<div class="pagination">${page==null?`<button data-page-group="${esc(group.id)}" data-page="0">Voir les ${examples.length} exemples</button>`:`<button data-page-group="${esc(group.id)}" data-page="${Math.max(0,page-1)}" ${page===0?'disabled':''}>Précédents</button><span>Page ${page+1} / ${Math.ceil(examples.length/25)}</span><button data-page-group="${esc(group.id)}" data-page="${page+1}" ${(page+1)*25>=examples.length?'disabled':''}>Suivants</button>`}</div>`:'';
    return `<details class="group ${severity(group)}" data-group="${esc(group.id)}" data-open="${esc(group.id)}" ${state.open.has(group.id)?'open':''}><summary><div><div class="badges"><span class="badge ${severity(group)}">${severityLabel(group)}</span><span class="badge">${esc(group.field_zone_label || group.family_label)}</span><span class="badge">${esc(group.code)}</span></div><h3>${esc(group.title)}</h3><p class="plain-explanation">${esc(group.field_explanation || group.impact || group.symptom)}</p><p>${esc(group.affected_label || group.metric)} · ${esc(action(group))}</p><p class="muted">${esc(group.evidence)}</p></div></summary><div class="group-body"><section><h3>Constat et chiffres</h3><p>${esc(group.field_explanation || group.field_impact || group.impact)}</p><p>${esc(group.symptom)}</p>${list(group.business_lines)}<p class="muted">${group.incident_count} diagnostics · Confiance : ${esc(group.confidence)}</p>${Object.keys(group.measurement_stats || {}).length?'<p class="muted">Les compteurs, plages et pistes de mesure figurent dans le bilan en haut du rapport.</p>':''}</section><div class="columns"><section><h3>Causes possibles</h3>${list(group.probable_causes)}</section><section><h3>Contrôles conseillés</h3>${list(group.checks)}</section></div><section class="evidence"><h3>Exemples réels <span class="muted">${examples.length} preuve(s) collectée(s)</span></h3>${selected.map(sample=>sampleHtml(sample,state.connected)).join('') || '<p class="muted">Aucun exemple individuel disponible.</p>'}${pagination}</section><details><summary>Détail complet des diagnostics regroupés</summary>${(group.incidents||[]).map(item=>`<article class="sample"><strong>${esc(item.start_time_str)} → ${esc(item.end_time_str)} · L.${item.first_line} à L.${item.last_line}</strong><p>${esc(item.title)} · ${item.count} occurrence(s) · ${esc(item.duration)}</p><p>${esc(item.summary)}</p><p>${esc(item.symptom)}</p><p class="muted">Confiance : ${esc(item.confidence)}</p>${list(item.probable_causes)}${list(item.checks)}</article>`).join('')}</details></div></details>`;
  }
  function pdfLines(data) {
    const result=[];
    const add=(text,kind='text')=>result.push({text:String(text??''),kind});
    add(data.source?.name || 'Trace analysée','title');
    add(`${data.source?.start || ''} → ${data.source?.end || ''} · ${data.source?.duration || ''} · Généré le ${data.generated_at}`);
    add(data.verdict?.title || 'Synthèse','section');add(data.verdict?.text);
    add(`${data.counts?.analyzed_boxes || 0} boîtes analysées · ${data.counts?.error || 0} types critiques · ${data.counts?.warning || 0} types en alerte · ${data.counts?.info || 0} types informatifs`,'metric');
    add('Bilan des mesures','section');
    add(measurementTotal(data.measurements || {}),'metric');add(globalMeasurementText(data.measurements || {}));
    add('Écart = mesure - dimension attendue dans la base de données (BdD). Tolérance : +/-3 mm inclus.');
    for(const name of ['length','width','height']) {
      const axis=data.measurements?.axes?.[name];if(!axis)continue;
      add(axis.label,'group');
      add(measurementCounts(axis),'metric');
      const bad=axis.anomalies,all=axis.all;
      if(bad.count){
        add(`Mauvaises mesures : ${bad.references} références ; plage ${range(bad)}.`);
        add(`Pire mesure en moins : ${extreme(bad.worst_under)} ; en trop : ${extreme(bad.worst_over)}. ${bad.under_count} trop petites ; ${bad.over_count} trop grandes.`);
        add(`Moyennes des mauvaises mesures : décalage signé ${signed(bad.mean_signed)} mm ; erreur moyenne ${number(bad.mean_abs)} mm, sans tenir compte du sens.`);
        add(`Erreur absolue des mauvaises mesures : min ${number(bad.min_abs)}, max ${number(bad.max_abs)} mm.`);
      }else add('Aucune mauvaise mesure.');
      if(all.count){
        add(`Toutes les mesures comparables : ${all.count} boîtes, ${all.references} références ; plage ${range(all)}.`);
        add(`Toutes les mesures : décalage moyen signé ${signed(all.mean_signed)} mm ; erreur moyenne ${number(all.mean_abs)} mm ; erreur absolue min ${number(all.min_abs)}, max ${number(all.max_abs)} mm.`);
      }else add('Aucune mesure comparable.');
      if(axis.bias)add(biasText(axis.bias));
      else for(const explanation of axis.interpretation || [])add('Piste à vérifier : '+explanation);
      for(const side of ['under','over']){
        const rows=data.measurement_references?.[name]?.[side] || [];
        if(rows.length)add(`${side==='under'?'Trop petites':'Trop grandes'} : ${rows.length} références ; les 3 plus grands écarts :`,'metric');
        for(const row of rows.slice(0,3))add(`${row.barcode} ${row.name} : ${row.count}/${row.total} boîtes (${number(row.percent)} %) ; plage ${range(row)} ; pire ${signed(row.worst)} mm.`);
      }
    }
    const excluded=Object.entries(data.measurements?.excluded||{}).filter(([,n])=>n).map(([key,n])=>`${exclusionLabels[key]||key} : ${n}`).join(' ; ');
    if(excluded)add('Exclus du bilan : '+excluded);
    if(data.camera?.available){add('Lecture des caméras','section');add(data.camera.note);for(const row of data.camera.chart||[])add(`${row.label} : ${row.success_count} lectures réussies — ${row.status_label}`);for(const row of data.camera.reader_stats||[])add(`${row.reader} : ${row.zero_code_label} lectures à 0 code ; caméras ${row.expected_cameras}`);}
    add('Diagnostics et contrôles prioritaires','section');
    for(const group of data.groups||[]) {
      add(`[${severityLabel(group)}] ${group.title}`,'group');add(`${group.affected_label || group.metric} · ${group.evidence}`);add(group.field_explanation||group.impact);add(group.summary);
      add('Action : '+action(group));for(const cause of group.probable_causes||[])add('Cause possible : '+cause);for(const check of group.checks||[])add('Contrôle : '+check);
      const samples=(group.examples||[]).filter(s=>(group.representative_ids||[]).includes(s.id));
      for(const sample of samples){add(`Exemple ${sample.time_str} · L.${sample.line} · ${sample.box||''} ${sample.barcode||''}`,'example');if(sample.measured){for(const [label,i] of [['Longueur T4C',2],['Largeur',0],['Hauteur',1]])add(`${label} : BdD ${sample.expected[i]} mm ; mesure ${sample.measured[i]} mm ; écart ${signed(sample.deltas[i])} mm.`);if(sample.t4t)add(`T4T (complément) : ${sample.t4t} mm ; diffT4 : ${signed(sample.diff_t4)} mm.`);}else add(sample.detail);for(const row of sample.context||[])add(`L.${row.line} ${row.text}`);}
    }
    return result;
  }
  /* PDF vectoriel autonome : accents WinAnsi, retours et fonds dimensionnes. */
  function buildPdf(data) {
    const encode=text=>String(text).replace(/→/g,'->').replace(/[−–—]/g,'-').replace(/’/g,"'").replace(/œ/g,'oe').replace(/[^\x20-\x7e\xa0-\xff]/g,' ');
    const escape=text=>encode(text).replace(/\\/g,'\\\\').replace(/\(/g,'\\(').replace(/\)/g,'\\)');
    const text=(value,x,y,size,bold=false)=>`BT /${bold?'F2':'F1'} ${size} Tf ${x} ${y} Td (${escape(value)}) Tj ET\n`;
    const wrap=(value,max)=>{const words=encode(value).split(/\s+/);const lines=[];let line='';for(let word of words){while(word.length>max){if(line){lines.push(line);line='';}lines.push(word.slice(0,max));word=word.slice(max);}if((line+' '+word).trim().length>max){lines.push(line);line=word;}else line=(line+' '+word).trim();}if(line)lines.push(line);return lines.length?lines:[''];};
    const pages=[];let body='',y=745;
    const header=()=>{body+='q 0.07 0.17 0.29 rg 36 778 523 42 re f Q\nq 1 1 1 rg\n'+text('TraceAlphaViewer — Rapport diagnostic',48,794,15,true)+'Q\n';};
    const finish=()=>{body+=text(`TraceAlphaViewer | page ${pages.length+1}`,42,28,8);pages.push(body);body='';y=745;header();};header();
    for(const item of pdfLines(data)) {
      const size=item.kind==='title'?16:item.kind==='section'?13:item.kind==='group'?11:9;
      const bold=item.kind!=='text';const lines=wrap(item.text,Math.floor(480/(size*.55)));
      const gap=size+5;const height=lines.length*gap+10;
      const reserve=['section','group'].includes(item.kind)?42:0;
      if(y-height-reserve<55 && height<680)finish();
      if(item.kind==='section'||item.kind==='group'||item.kind==='metric'){body+=`q ${item.kind==='section'?'0.88 0.93 0.98':'0.95 0.96 0.98'} rg 38 ${y-height+3} 519 ${height} re f Q\n`;}
      for(const line of lines){if(y-gap<55)finish();body+=text(line,48,y-gap+4,size,bold);y-=gap;}y-=10;
    }
    finish();const objects=[];const add=value=>(objects.push(value),objects.length);
    const f1=add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>');const f2=add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>');const ids=[];
    for(const page of pages){const stream=add(`<< /Length ${page.length} >>\nstream\n${page}endstream`);ids.push(add(`<< /Type /Page /Parent PARENT 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 ${f1} 0 R /F2 ${f2} 0 R >> >> /Contents ${stream} 0 R >>`));}
    const parent=add(`<< /Type /Pages /Kids [${ids.map(id=>`${id} 0 R`).join(' ')}] /Count ${ids.length} >>`);const catalog=add(`<< /Type /Catalog /Pages ${parent} 0 R >>`);for(const id of ids)objects[id-1]=objects[id-1].replace('PARENT',parent);
    let pdf='%PDF-1.4\n';const offsets=[0];objects.forEach((object,index)=>{offsets.push(pdf.length);pdf+=`${index+1} 0 obj\n${object}\nendobj\n`;});const offset=pdf.length;pdf+=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n`;offsets.slice(1).forEach(value=>pdf+=String(value).padStart(10,'0')+' 00000 n \n');pdf+=`trailer\n<< /Size ${objects.length+1} /Root ${catalog} 0 R >>\nstartxref\n${offset}\n%%EOF`;
    return Uint8Array.from(pdf,c=>c.charCodeAt(0));
  }
  function downloadPdf(data) {
    const blob=new Blob([buildPdf(data)],{type:'application/pdf'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='diagnostic-terrain.pdf';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  scope.TraceReport={mount,buildPdf,pdfLines};
})(globalThis);
