/* Affichage partage entre le rapport React et le secours HTML autonome. */
(function (scope) {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => value == null ? '—' : Number(value).toLocaleString('fr-FR', {minimumFractionDigits:1, maximumFractionDigits:1});
  const signed = value => value == null ? '—' : `${value > 0 ? '+' : ''}${number(value)}`;
  const severity = group => group.field_severity || group.severity;
  const referenceRejection = code => ['REFERENCE_ABSENT','REFERENCE_NON_ALPHATISABLE'].includes(code);
  const structuredProof = code => referenceRejection(code) || ['C2_SIGNAL_ANOMALY','C3_SIGNAL_ANOMALY','C5_SIGNAL_ANOMALY','diffT4','MOTOR_COMM','DP_MISSING','CAMERA_CODE_MODE'].includes(code);
  const criticalRobot = group => Number(group?.metrics?.day?.count||0)>=10;
  const severityLabel = group => ({error:'Critique',warning:'Alerte',info:'Info'}[severity(group)] || 'Info');
  const action = group => group.field_action || group.action || group.title;
  const colors = {length:'#A78BFA',width:'#14B8A6',height:'#FDE047'};
  const axisInfo = {length:{label:'Longueur',source:'T4/C6 · T4C',under:'Trop courtes',over:'Trop longues'},width:{label:'Largeur',source:'T5/C9',under:'Trop étroites',over:'Trop larges'},height:{label:'Hauteur',source:'T5/LzB',under:'Trop basses',over:'Trop hautes'}};
  const axisTolerance = (summary,name) => summary?.tolerances_mm?.[name] ?? summary?.axes?.[name]?.tolerance_mm ?? summary?.tolerance_mm ?? 3;
  const thresholdText = summary => `Seuils d’alerte (écart absolu) : longueur > ${axisTolerance(summary,'length')} mm · largeur > ${axisTolerance(summary,'width')} mm · hauteur > ${axisTolerance(summary,'height')} mm.`;
  const isPrimary = row => row.display_primary ?? (row.total>0 && row.count*10>=row.total);
  const primaryRows = (data,axis,side) => (data?.measurement_references?.[axis]?.[side]||[]).filter(isPrimary);
  const displayExtreme = (data,axis,side) => {const rows=primaryRows(data,axis,side);return rows.length?extreme(rows[0].worst):data?.measurements?.axes?.[axis]?.anomalies?.[side+'_count']?'Aucun produit à 10 %':'Aucune';};
  const fullMeasurement = sample => Number.isInteger(sample.display_frame_index) && sample.display_frame_index>=0 && sample.display_line>0 && ['length','width','height'].every(axis=>sample.sources?.[axis]>0) && sample.measured?.length===3 && sample.measured.every(value=>value>0) && sample.expected?.length===3 && sample.expected.every(value=>value>0);
  const list = values => `<ul>${(values || []).map(value => `<li>${esc(value)}</li>`).join('')}</ul>`;
  const exclusionLabels = {orientation:'orientations probables',orientation_uncertain:'orientations indécidables',camera_unconfirmed:'identifications caméra non confirmées',invalid:'mesures invalides',incomplete:'mesures incomplètes',reference_absent:'références BdD absentes',ambiguous:'identités ambiguës',unknown:'UNKNOWN sans produit identifié',identity_unconfirmed:'identifications non confirmées',reference_conflict:'références contradictoires',t4c_absent:'longueur T4C absente'};
  const hasRepeatedOffsets = axis => Object.values(axis.recurrence || {}).some(item => item.cluster?.similar);
  function recurrenceEntries(axis) {
    return ['under','over'].map(side=>{
      const item=axis.recurrence?.[side],cluster=item?.cluster,frequent=item?.frequencies?.[0];
      if(!frequent)return null;
      const sign=side==='under'?'en moins':'en trop';
      const text=cluster?`${cluster.bad_count} boîtes en défaut autour de ${signed(cluster.center)} mm ${sign} (±1 mm). ${cluster.similar?`Répétition sur ${cluster.repeated_references} produit(s).`:'Répétition par produit non confirmée.'}${cluster.limited?' Effectif limité.':''}`:`Écart le plus fréquent ${sign} : ${signed(frequent.delta)} mm, ${frequent.count} boîte(s). Répétition par produit non confirmée.`;
      return {side,count:cluster?.bad_count??item.count,text};
    }).filter(Boolean);
  }
  const recurrenceBrief = axis => recurrenceEntries(axis).map(item=>item.text);
  function recurrenceHtml(axis) {
    const brief=recurrenceBrief(axis);if(!brief.length)return '';
    return `<div class='recurrence'><strong>${hasRepeatedOffsets(axis)?'Répétition observée':'Écarts observés'}</strong>${brief.map(text=>`<p>${esc(text)}</p>`).join('')}</div>`;
  }
  function groupRecurrenceHtml(group) {
    const names={T4_LENGTH:['length'],T5_WIDTH:['width'],T5_HEIGHT:['height'],GLOBAL:['length','width','height']}[group.code]||[];
    const rows=names.flatMap(name=>{const axis=group.measurement_stats?.axes?.[name];return axis?recurrenceEntries(axis).map(item=>({...item,name})):[];});
    rows.sort((a,b)=>b.count-a.count||['length','width','height'].indexOf(a.name)-['length','width','height'].indexOf(b.name)||['under','over'].indexOf(a.side)-['under','over'].indexOf(b.side));
    return rows.length?`<div class='trace-measurement-summary'><p class='muted'>Observations sur toutes les boîtes comparables de la trace.</p>${rows.map(item=>`<p class='group-recurrence'><strong>${axisInfo[item.name].label}</strong> · ${esc(item.text)}</p>`).join('')}</div>`:'';
  }
  function distributionHtml(axis,name,expanded=false) {
    const rows=axis.frequencies || [];
    if(!rows.length)return '';
    const visible=expanded?rows:rows.slice(0,5),limited=rows.length>5;
    const share=visible.reduce((sum,row)=>sum+row.percent,0);
    return `<div class='distribution' data-distribution='${name}'><h4>Répartition de toutes les mesures comparables</h4><p class="muted">Les mesures conformes sont incluses. Chaque boîte est comptée une fois.</p>${limited?`<p class='distribution-caption'>${expanded?`${rows.length} écarts observés · liste complète`:`Les 5 écarts les plus fréquents · ${number(share)} % des boîtes comparables`}</p>`:''}<div class="table-wrap"><table id='distribution-${name}' class="measurement-distribution"><thead><tr><th>Écart signé</th><th>Boîtes</th><th>Part des comparables</th></tr></thead><tbody>${visible.map(row=>`<tr><td>${signed(row.delta)} mm</td><td>${row.count}</td><td>${number(row.percent)} %</td></tr>`).join('')}</tbody></table></div>${limited?`<button class='distribution-toggle' data-distribution-axis='${name}' aria-expanded='${expanded}' aria-controls='distribution-${name}'>${expanded?'Réduire la liste':`Afficher toute la répartition (${rows.length} écarts)`}<svg aria-hidden='true' viewBox='0 0 16 16' width='16' height='16' fill='none' stroke='currentColor' stroke-width='1.6'><path d='${expanded?'M4 10l4-4 4 4':'M4 6l4 4 4-4'}'/></svg></button>`:''}</div>`;
  }
  function observationText(row) {
    const expected=row.expected || [];
    const values=`BdD ${expected[2]} × ${expected[0]} × ${expected[1]} mm (longueur × largeur × hauteur) : ${row.total} mesures, plage ${signed(row.min_signed)} à ${signed(row.max_signed)} mm.`;
    const nearby=row.center==null?'':` ${row.close_count}/${row.total} (${number(row.close_percent)} %) à ±1 mm autour de ${signed(row.center)} mm.`;
    const conclusion=row.repeated?' Écarts proches sur ce produit.':row.total===1?' Une seule mesure : la répétition n’est pas confirmée.':'';
    const spread=row.dispersed?` Dispersion observée sur ce produit : la fenêtre de 2 mm la plus fournie contient ${row.window_count}/${row.total} mesures (${number(row.window_percent)} %).`:'';
    return values+nearby+conclusion+spread+(row.limited?' Effectif limité.':'');
  }
  function productObservationHtml(row,state,axis) {
    const observations=row?.observations||[];if(!observations.length)return '';
    const representatives=(row.representative_ids||[]).map(id=>state.measurementExamples.get(id)).filter(Boolean);
    return `<details class='product-observations' data-open='product-${axis}-${esc(row.barcode)}'><summary>Répétitions et variantes de ce produit</summary>${observations.length>1?'<p class=variant-note>Plusieurs dimensions BdD : les variantes sont analysées séparément.</p>':''}${observations.map(item=>`<p>${esc(observationText(item))}</p>`).join('')}${representatives.length?`<details class='comparison-examples'><summary>Exemples représentatifs, avec les conformes voisines</summary>${representatives.map(sample=>sampleHtml(sample,state.connected,axis,state.tolerances)).join('')}</details>`:''}</details>`;
  }
  function direction(name, value) {
    if (!value) return 'Sans biais moyen';
    const labels = {length:['trop court','trop long'],width:['trop étroit','trop large'],height:['trop bas','trop haut']};
    return `${number(Math.abs(value))} mm ${labels[name][value > 0 ? 1 : 0]}`;
  }
  function measurementHtml(summary,data,state) {
    const axes=['length','width','height'].filter(name=>summary?.axes?.[name]);if(!axes.length)return '<p>Aucune analyse de mesure disponible.</p>';
    const excluded=Object.entries(summary.excluded||{}).filter(([,count])=>count);
    return `<div class='measurement-intro'><p>${esc(globalMeasurementText(summary))}</p><p class='muted'>${esc(measurementTotal(summary))}</p><p class='muted'>Une boîte compte une fois. La mesure Alpha est comparée à la BdD du même produit.</p><p class='muted'>${esc(thresholdText(summary))}</p></div><div class='axis-grid'>${axes.map(name=>{
      const axis=summary.axes[name],bad=axis.anomalies,info=axisInfo[name];
      return `<article class='axis' data-axis='${name}' style='--axis:${colors[name]}'><div class='axis-heading'><h3>${info.label}</h3><span class='muted'>${info.source}</span></div><p class='axis-count'>${axis.all.count?`<strong>${bad.count}</strong> boîtes hors tolérance`:'Comparaison indisponible'}</p><p class='muted'>${axis.all.count?`sur ${axis.all.count} comparables · ${number(axis.all.outside_percent)} %`:'Aucune boîte comparable'}</p><p class='axis-threshold'><strong>À vérifier : écart > ${axisTolerance(summary,name)} mm</strong> en valeur absolue.</p><div class='measure-directions'>${['under','over'].map(side=>`<button data-measure-axis='${name}' data-measure-side='${side}' ${bad[side+'_count']?'':'disabled'}><span>${info[side]} · ${bad[side+'_count']}</span><small>Écart marquant (produits ≥ 10 %) : ${displayExtreme(data,name,side)}</small></button>`).join('')}</div><p class='muted'>Produits concernés : ${bad.references} sur ${axis.all.references} produits distincts comparables.</p>${recurrenceHtml(axis)}${distributionHtml(axis,name,state.distributions.has(name))}</article>`;
    }).join('')}</div>${data&&state?referenceHtml(data,state):''}<details class='measurement-exclusions'><summary>Boîtes non comparées · ${summary.excluded_count||0}</summary><p>Ces boîtes ne sont comptées ni conformes ni hors tolérance. Reconnaissance CB1/CB2 et dimensions fiables sont nécessaires ; le sens doit être compatible avec les mesures.</p>${excluded.length?`<ul>${excluded.map(([key,count])=>`<li><strong>${count}</strong> · ${esc(exclusionLabels[key]||key)}</li>`).join('')}</ul>`:'<p>Aucune boîte exclue.</p>'}</details>`;
  }
  function referenceHtml(data,state) {
    const selected=state.measurementSelection;if(!selected)return '';
    const {axis,side,barcode,page}=selected,info=axisInfo[axis],grouped=side.endsWith('_group');
    const allRows=data.measurement_references?.[axis]?.[side]||[],row=allRows.find(item=>item.barcode===barcode);
    const rows=grouped?allRows:allRows.filter(isPrimary),rare=grouped?[]:allRows.filter(item=>!isPrimary(item));
    const items=barcode?(row?.sample_ids||[]).map(id=>state.measurementExamples.get(id)).filter(Boolean):rows;
    const visible=items.slice(page*25,(page+1)*25),rarePage=selected.rarePage||0;
    const center=data.measurements.axes[axis].recurrence?.[side.replace('_group','')]?.cluster?.center;
    const title=`${info.label} · ${grouped?`Écarts proches de ${signed(center)} mm`:info[side]}`;
    const table=values=>`<div class='table-wrap'><table><thead><tr><th>Produit / référence</th><th>Boîtes concernées</th><th>Pire écart</th></tr></thead><tbody>${values.map(item=>`<tr><td><strong>${esc(item.name||'Produit identifié')}</strong><br><button class='reference-link' data-measure-barcode='${esc(item.barcode)}'>${esc(item.barcode)}</button>${item.variant_count>1?'<p class=variant-note>Plusieurs variantes BdD</p>':''}</td><td>${item.count} sur ${item.total}<br><span class='muted'>${number(item.percent)} % des comparables de ce produit</span></td><td><strong>${signed(item.worst)} mm</strong></td></tr>`).join('')}</tbody></table></div>`;
    const rareHtml=!barcode&&rare.length?`<details class='rare-products' data-open='rare-${axis}-${side}'><summary>Cas rares (&lt; 10 %) · ${rare.length} produits</summary><p class='muted'>Ces défauts restent inclus dans tous les calculs. Le seuil de 10 % porte sur les boîtes comparables de chaque produit, pour ce côté.</p>${table(rare.slice(rarePage*25,(rarePage+1)*25))}<div class='pagination'><button class='small' data-measure-rare-page='${rarePage-1}' ${rarePage===0?'disabled':''}>Précédents</button><span>Page ${rarePage+1}/${Math.ceil(rare.length/25)} · ${rare.length} produits rares</span><button class='small' data-measure-rare-page='${rarePage+1}' ${(rarePage+1)*25>=rare.length?'disabled':''}>Suivants</button></div></details>`:'';
    return `<section class='measurement-reference-list' aria-label='Détail des mesures'><h3>${esc(title)}</h3><p class='muted'>${grouped?'Les mesures conformes voisines sont incluses.':`Liste principale : au moins 10 % de défauts de ce côté par produit. ${rows.length} produits retenus ; ${rare.length} produits dans les cas rares. Les totaux et distributions incluent tous les défauts.`}</p>${barcode?`<div class='product-heading'><div><h4>${esc(row?.name||'Produit identifié')}</h4><p class='muted'>Référence ${esc(barcode)}</p></div><button class='small' data-measure-back>Retour aux références</button></div><h4>${grouped?'Toutes les mesures comparables de ce produit':'Boîtes hors tolérance de ce côté'}</h4>`:''}${!items.length?`<p>${barcode||grouped?'Aucune boîte concernée.':'Aucun produit n’atteint 10 % de défauts de ce côté. Consulter les cas rares.'}</p>`:barcode?`<div class='reference-proofs'>${visible.map(sample=>sampleHtml(sample,state.connected,axis,state.tolerances)).join('')}</div>${productObservationHtml(row,state,axis)}`:table(visible)}<div class='pagination'><button class='small' data-measure-page='${page-1}' ${page===0?'disabled':''}>Précédents</button><span>Page ${page+1}/${Math.max(1,Math.ceil(items.length/25))} · ${items.length} ${barcode?'boîtes':'produits'}</span><button class='small' data-measure-page='${page+1}' ${(page+1)*25>=items.length?'disabled':''}>Suivants</button><button class='small' data-measure-close>Fermer la liste</button></div>${rareHtml}</section>`;
  }
  const extreme = value => value == null ? 'Aucune' : `${signed(value)} mm`;
  const measurementCounts = axis => axis.all.count ? `Bonnes mesures : ${axis.all.within_count}/${axis.all.count} (${number(axis.all.within_percent)} %) · Mauvaises mesures : ${axis.all.outside_count}/${axis.all.count} (${number(axis.all.outside_percent)} %)` : 'Aucune mesure comparable pour cet axe.';
  const measurementTotal = summary => `${summary.cycle_count || 0} cycles de boîtes analysés sur T5 · ${summary.comparable_count || 0} comparables · ${summary.excluded_count || 0} exclus`;
  const globalMeasurementText = summary => !summary.global?.count ? 'Aucune boîte ne réunit les conditions de comparaison. Consulter les boîtes non comparées.' : summary.global.outside_count ? `${summary.global.outside_count} boîtes hors tolérance sur ${summary.global.count} comparables (${number(summary.global.outside_percent)} %). Une boîte en défaut sur plusieurs dimensions compte une seule fois.` : `Les ${summary.global.count} boîtes comparables sont conformes sur les trois dimensions.`;
  function orientationMatchesHtml(sample) {
    if(sample.code!=='ORIENTATION')return '';
    const uncertain=sample.orientation_state==='orientation_uncertain';
    return `<div class='orientation-explanation'><p><strong>${uncertain?'Orientation indécidable':'Orientation probable d’après les dimensions'}</strong> · ${uncertain?'La présentation normale et une autre orientation obtiennent le même score.':'Une autre orientation explique mieux les mesures que la présentation normale.'} Le sens physique reste à vérifier.</p>${sample.orientation_matches?.length?`<h4>${uncertain?'Présentations à égalité':'Présentations expliquant le mieux les mesures'}</h4><div class='table-wrap'><table class='orientation-matches'><thead><tr><th>Longueur</th><th>Largeur</th><th>Hauteur</th><th>Écart cumulé</th></tr></thead><tbody>${sample.orientation_matches.map(match=>`<tr><td>${match.dimensions[2]} mm</td><td>${match.dimensions[0]} mm</td><td>${match.dimensions[1]} mm</td><td>${match.error_mm} mm</td></tr>`).join('')}</tbody></table></div><p class='muted'>Écart cumulé : somme des différences absolues entre les trois mesures et cette permutation BdD. Ce score ne certifie pas l’orientation physique.</p>`:''}</div>`;
  }
  const integer = value => Number(value||0).toLocaleString('fr-FR');
  function unknownCounter(unknown) {
    if(!unknown || !('total' in unknown))return '';
    const count=Number(unknown.count),total=Number(unknown.total);
    const available=Number.isFinite(count)&&count>=0&&Number.isFinite(total)&&total>0;
    const tone=!available?'is-neutral':count*100<total*8?'is-good':count*100<=total*12?'is-warning':'is-bad';
    return `<div class='unknown-counter ${tone}' role='group' aria-label='Boîtes finales UNKNOWN confirmées CB1 et CB2'><span class='unknown-caption'>UNKNOWN · CB1 + CB2</span><span class='unknown-values'><strong>${integer(unknown.count)} <small>/ ${integer(unknown.total)}</small></strong><span class='unknown-percent'>${available?number(100*count/total)+' %':'Indisponible'}</span></span></div>`;
  }
  function proofHtml(context,connected) {
    if(!context?.length)return 'Contexte indisponible.';
    return context.map(row=>`${row.navigation_id?`<button class='trace-line' data-source-navigate='${esc(row.navigation_id)}' ${connected?'':'disabled'} aria-label='Voir ${esc(row.source_label||`L.${row.line}`)} dans AlphaViewer'>${esc(row.source_label||`L.${row.line}`)}</button>`:esc(row.source_label||`L.${row.line}`)}  ${esc(row.text)}`).join('\n');
  }
  function seriesHtml(group,state) {
    return group.series.map((series,index)=>{
      const samples=group.examples.slice(series.example_start,series.example_start+series.example_count);
      const label=`${integer(samples.length)} exemple(s) présenté(s) · ${integer(series.count)} occurrence(s)`;
      return `<details class='incident-series' data-open='series-${esc(group.id)}-${index}'><summary><strong>${integer(series.count)} ${series.distinct_events?'demandes distinctes':'occurrence(s)'}</strong><span>${esc(series.start_time_str)} → ${esc(series.end_time_str)} · ${esc(series.duration)}</span><span class='muted'>${esc(series.source_name||'Source')} · L.${series.source_first_line||series.first_line} à L.${series.source_last_line||series.last_line} · ${label}</span></summary><p>${esc(series.summary)}</p>${samples.map(sample=>sampleHtml({...sample,detail:structuredProof(group.code)?sample.detail:''},state.connected,'',state.tolerances)).join('')}</details>`;
    }).join('');
  }
  function sampleHtml(sample,connected,axis='',tolerances) {
    const measured=Array.isArray(sample.measured),complete=measured&&fullMeasurement(sample),orientation=sample.code==='ORIENTATION';
    const line=measured?sample.display_line:sample.line;
    const available=measured?complete:Boolean(line);
    const measures=measured?`<div class='table-wrap'><table class='box-measurements'><thead><tr><th>Dimension</th><th>BdD</th><th>Mesure Alpha</th>${orientation?'':'<th>Écart</th>'}</tr></thead><tbody>${[['Longueur',2,'length'],['Largeur',0,'width'],['Hauteur',1,'height']].map(([label,i,name])=>`<tr class='${name===axis?'selected-axis':''}'><td>${label}</td><td>${sample.expected[i]} mm</td><td>${sample.measured[i]} mm</td>${orientation?'':`<td class='${Math.abs(sample.deltas[i])>(sample.tolerances_mm?.[name]??tolerances?.[name]??3)?'measure-bad':'measure-good'}'>${signed(sample.deltas[i])} mm</td>`}</tr>`).join('')}</tbody></table></div>${orientation?orientationMatchesHtml(sample):`<p class='muted'>Écart positif : mesure au-dessus de la BdD. Écart négatif : mesure en dessous.</p>`}`:`<p>${esc(sample.detail)}</p>`;
    return `<article class='sample'><div class='sample-head'><div><strong>${esc(sample.display_time_str||sample.time_str)}</strong><p class='muted'>${esc([sample.box,sample.barcode,sample.source_label].filter(Boolean).join(' · '))}</p></div><button class='small' data-navigate='${esc(sample.id)}' ${axis?`data-navigate-axis='${axis}'`:''} ${available?'':'data-missing-source'} ${connected&&available?'':'disabled'}>${measured?'Voir la boîte mesurée dans AlphaViewer':'Voir dans AlphaViewer'}</button></div>${measured?`<p class='sample-state'>${complete?'État après les trois mesures : longueur, largeur et hauteur.':'État complet indisponible : régénérer le rapport depuis la trace.'}${sample.final===false?' Mesure antérieure, hors effectif final.':''}${sample.invalid?' Mesure invalide, exclue du bilan.':''}</p>`:''}${sample.rejected_dimensions?`<p>Produit identifié puis rejeté pour dimensions : ${esc(sample.current_reference)}</p>`:''}${measures}<details class='sample-technical' data-open='proof-${esc(sample.id)}'><summary>Sources et contexte technique</summary>${line?`<p class='muted'>État affiché : ${esc(sample.display_source_label||sample.source_label||`L.${line}`)}.</p>`:''}${sample.t4t?`<p>T4T (complément) : ${sample.t4t} mm ; diffT4 ${signed(sample.diff_t4)} mm.</p>`:''}${sample.sources?`<p>Sources : ${measured?`T4C ${esc(sample.source_labels?.length||`L.${sample.sources.length}`)} · C9 ${esc(sample.source_labels?.width||`L.${sample.sources.width}`)} · hauteur ${esc(sample.source_labels?.height||`L.${sample.sources.height}`)} · BdD ${esc(sample.source_labels?.bdd||`L.${sample.sources.bdd}`)} · identification ${esc(sample.source_labels?.identity||`L.${sample.sources.identity}`)}`:Object.entries(sample.sources).map(([label,line])=>`${esc(label)} ${esc(sample.source_labels?.[label]||`L.${line}`)}`).join(' · ')}.</p>`:''}<pre>${proofHtml(sample.context,connected)}</pre></details></article>`;
  }
  function sourcePeriodText(source) {
    return source?.dates_available===false?'Dates indisponibles — rechargez la trace':`${source?.start||''} → ${source?.end||''}`;
  }
  function mount(root, data) {
    const groups = (data.groups || []).filter(group=>!data.orientation_references || group.code!=='ORIENTATION');
    const indexed = groups.map(group => ({group,search:JSON.stringify(group).toLocaleLowerCase('fr')}));
    const state = {search:'',family:'all',level:'all',pages:{},open:new Set(['measurements','camera']),connected:false,message:''};
    state.distributions=new Set();
    state.tolerances=data.measurements?.tolerances_mm;
    state.measurementSelection=null;
    state.orientations={probable:{page:0,barcode:''},uncertain:{page:0,barcode:''}};
    for(const category of data.orientation_categories||[])state.orientations[category.id]={page:0,barcode:''};
    state.measurementExamples=new Map((data.measurement_examples || []).map(sample=>[sample.id,sample]));
    const local = location.protocol==='http:' && location.hostname==='127.0.0.1' && /\/view\.html$/.test(location.pathname);
    const controller = new AbortController();
    let disposed = false, debounce;
    function render() {
      root.querySelectorAll('details[data-open]').forEach(node => node.open ? state.open.add(node.dataset.open) : state.open.delete(node.dataset.open));
      const filtered = indexed.filter(({group,search}) => (state.family==='all'||group.family===state.family) && (state.level==='all'||severity(group)===state.level) && (!state.search||search.includes(state.search.toLocaleLowerCase('fr')))).map(x => x.group);
      const counts = data.counts || {};
      const source = data.source || {};
      root.innerHTML = `<main class='report ${data.camera?.available?'has-sidebar':''}'><header class='hero'><div class='hero-top'><div class='hero-brand'><span class='brand-mark' aria-hidden='true'><svg viewBox='0 0 24 24' width='22' height='22' fill='none' stroke='currentColor' stroke-width='1.6'><path d='M4 18V6m4 12v-4m4 4V9m4 9V5m4 13v-7M3 21h18'/></svg></span><span class='eyebrow'>TraceAlphaViewer</span></div><p class='status' role='status'>${esc(state.message||(state.connected?'Liaison avec la trace ouverte dans AlphaViewer.':'Consultation autonome · navigation viewer indisponible.'))}</p></div><div class='hero-title'><h1>Rapport d’analyse Alpha</h1>${identityHtml(source.identity)}</div><div class='hero-footer'><div class='hero-meta'><div class='meta-item hero-file'><span>Trace analysée</span><strong class='source-name'>${esc(source.name||'Trace analysée')}</strong></div><div class='meta-item hero-period'><span>Période observée</span><strong>${esc(sourcePeriodText(source))}</strong></div><div class='meta-item hero-duration'><span>Durée</span><strong>${esc(source.duration)}</strong></div></div><button class='primary' data-pdf><svg aria-hidden='true' viewBox='0 0 24 24' width='20' height='20' fill='none' stroke='currentColor' stroke-width='1.7'><path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/><path d='M14 2v6h6M12 11v7m-3-3 3 3 3-3'/></svg>Exporter PDF</button></div></header><div class='report-layout ${data.camera?.available?'has-camera':''}'><div class='report-content'><section class='section priorities'><div class='priority-heading'><div class='section-heading'><span class='eyebrow'>Synthèse terrain</span><h2>À vérifier en premier</h2><div class='priority-totals'><span><b>${counts.error||0}</b> problèmes critiques</span><span><b>${counts.warning||0}</b> alertes</span><span><b>${integer(counts.analyzed_boxes)}</b> boîtes observées</span></div></div>${unknownCounter(data.unknown)}</div><p class='priority-intro'>${esc(data.verdict?.text)}</p><div class='priority-grid'>${(data.priority||[]).slice(0,3).map((group,i)=>`<button data-priority='${esc(group.id)}'><span class='priority-number'>${i+1}</span><span class='badge ${severity(group)}'>${esc(severityLabel(group))}</span><strong>${esc(group.title)}</strong><span>${group.priority_lines?group.priority_lines.map(esc).join('<br>'):esc(group.field_explanation||group.impact)}</span><span class='priority-action'><b>Premier contrôle</b><br>${esc(action(group))}</span></button>`).join('')||'<p>Aucun problème prioritaire détecté.</p>'}</div></section><details class='section' data-open='measurements' ${state.open.has('measurements')?'open':''}><summary>Bilan des mesures de la trace <span class='muted'>Longueur · Largeur · Hauteur</span></summary>${measurementHtml(data.measurements,data,state)}</details>${orientationHtml(data,state)}<section class='diagnostic-list'><h2>Tous les diagnostics</h2><p class='muted'>Choisir un problème pour consulter ses contrôles et ses exemples. Les chiffres des mesures sont regroupés dans le bilan ci-dessus.</p><div class='filters'><input type='search' aria-label='Rechercher un diagnostic' placeholder='Rechercher un problème, une référence…' value='${esc(state.search)}'><select aria-label='Niveau' data-level>${[['all','Tous les niveaux'],['error','Critiques'],['warning','Alertes'],['info','Informations']].map(([key,label])=>`<option value='${key}' ${state.level===key?'selected':''}>${label}</option>`).join('')}</select><select aria-label='Famille' data-family>${(data.families||[]).filter(item=>item.id!=='critical').map(item=>`<option value='${item.id}' ${state.family===item.id?'selected':''}>${esc(item.label)}</option>`).join('')}</select></div><p id='problems' class='muted'>${filtered.length} type(s) de problème affichés sur ${groups.length}</p>${filtered.map(group=>groupHtml(group,state)).join('')||'<div class=empty>Aucun diagnostic pour ces critères.</div>'}</section><details class='section' data-open='zones' ${state.open.has('zones')?'open':''}><summary>Répartition par zone</summary>${list((data.zones||[]).map(zone=>`${zone.label||zone.family} : ${zone.occurrences} occurrences, ${zone.errors} critiques, ${zone.warnings} alertes`))}</details></div>${data.camera?.available?`<aside class='camera-sidebar' aria-label='Lecture des caméras'>${cameraHtml(data.camera,state.open.has('camera'),groups)}</aside>`:''}</div><p class='footer'>Les constats proviennent de la trace. Les causes et pistes de réglage restent à confirmer sur la machine. Généré le ${esc(data.generated_at)}.</p></main>`;
      root.querySelectorAll('details[data-open]').forEach(node=>node.open=state.open.has(node.dataset.open));
      renderRobotAlert();
    }
    function renderRobotAlert() {
      const group=groups.find(item=>item.code==='DemVidageComplet');
      if(!criticalRobot(group))return;
      if((data.priority||[]).slice(0,3).some(item=>item.code==='DemVidageComplet'))return;
      root.querySelector('.priority-intro')?.insertAdjacentHTML('beforebegin',`<button class='robot-drain-alert ${severity(group)}' data-priority='${esc(group.id)}'><strong>Vidage complet T5 demandé par le robot · ${esc(severityLabel(group))}</strong><span class='robot-total'>${esc(group.summary)}</span><span>${esc(group.trace_period||'Dates indisponibles ; rechargez la trace.')}</span><span>Voir le détail par jour →</span></button>`);
    }
    function refreshStatus() {
      root.querySelectorAll('[data-navigate],[data-source-navigate]').forEach(button => button.disabled=!state.connected || button.hasAttribute('data-missing-source'));
      const label = root.querySelector('.status');
      if(label) label.textContent = state.message || (state.connected?'Liaison avec la trace ouverte dans AlphaViewer.':'La trace source est fermée ou la liaison est indisponible.');
    }
    async function status() {
      if(!local || disposed) return;
      try { const response=await fetch('status',{signal:controller.signal}); state.connected=response.ok && (await response.json()).connected; }
      catch { state.connected=false; }
      if(!disposed) refreshStatus();
    }
    async function navigateSample(id,axis) {
      const sample=state.measurementExamples.get(id);
      if(!id || ((axis || sample?.code==='ORIENTATION') && !fullMeasurement(sample||{}))) {
        state.message='État complet indisponible. Rouvrir la trace et régénérer le rapport pour afficher les trois mesures.';refreshStatus();return;
      }
      if(!local || !state.connected) {
        state.message='Le détail reste consultable ; la trace source est fermée ou la liaison avec AlphaViewer est indisponible.';refreshStatus();return;
      }
      state.message='Recherche de cet exemple dans AlphaViewer…';refreshStatus();
      try {
        const response=await fetch('navigate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sample_id:id,...(axis?{axis}:{})}),signal:controller.signal});
        const result=await response.json();
        state.message=result.ok?`AlphaViewer positionné à la ligne ${result.line}.`:(result.error || 'Navigation indisponible.');
      } catch {state.message='La trace source est fermée ou remplacée. Rouvrir le rapport depuis la bonne trace.';state.connected=false;}
      if(!disposed)refreshStatus();
    }
    async function click(event) {
      const button=event.target.closest('button'); if(!button) return;
      if(button.hasAttribute('data-pdf')) {downloadPdf(data);return;}
      if(button.dataset.distributionAxis){const axis=button.dataset.distributionAxis;state.distributions.has(axis)?state.distributions.delete(axis):state.distributions.add(axis);render();root.querySelector(`[data-distribution-axis='${axis}']`)?.focus({preventScroll:true});return;}
      if(button.dataset.orientationBarcode){const kind=button.dataset.orientationKind,row=data.orientation_references?.[kind]?.find(row=>row.barcode===button.dataset.orientationBarcode);state.orientations[kind]={page:0,barcode:button.dataset.orientationBarcode};{const detail=kind==='probable'?root.querySelector('.orientation-all'):root.querySelector(`[data-orientation-category='${kind}']`);if(detail)detail.open=true;}render();await navigateSample(row?.navigation_sample_id);return;}
      if(button.hasAttribute('data-orientation-back')){state.orientations[button.dataset.orientationKind]={page:0,barcode:''};render();return;}
      if(button.hasAttribute('data-orientation-page')){state.orientations[button.dataset.orientationKind].page=Number(button.dataset.orientationPage);render();return;}
      if(button.dataset.measureAxis){state.measurementSelection={axis:button.dataset.measureAxis,side:button.dataset.measureSide,page:0,barcode:''};render();root.querySelector('.measurement-reference-list')?.scrollIntoView({block:'nearest'});return;}
      if(button.hasAttribute('data-measure-close')){state.measurementSelection=null;render();return;}
      if(button.hasAttribute('data-measure-back')){state.measurementSelection.barcode='';state.measurementSelection.page=0;render();return;}
      if(button.dataset.measureBarcode){
        const {axis,side}=state.measurementSelection;
        const row=data.measurement_references?.[axis]?.[side]?.find(item=>item.barcode===button.dataset.measureBarcode);
        state.measurementSelection.barcode=button.dataset.measureBarcode;state.measurementSelection.page=0;render();
        if(side==='under'||side==='over')await navigateSample(row?.navigation_sample_id,axis);
        return;
      }
      if(button.hasAttribute('data-measure-rare-page')){state.measurementSelection.rarePage=Number(button.dataset.measureRarePage);render();return;}
      if(button.hasAttribute('data-measure-page')){state.measurementSelection.page=Number(button.dataset.measurePage);render();return;}
      if(button.dataset.navigate) {
        await navigateSample(button.dataset.navigate,button.dataset.navigateAxis);
        return;
      }
      if(button.dataset.sourceNavigate){await navigateSample(button.dataset.sourceNavigate);return;}
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
  function orientationRowsHtml(data,state,kind,preview=false,previewRows=null) {
    const rows=previewRows||data.orientation_references?.[kind]||[],selection=state.orientations[kind];
    const row=rows.find(row=>row.barcode===selection.barcode);
    const items=selection.barcode?(row?.sample_ids||[]).map(id=>state.measurementExamples.get(id)).filter(Boolean):rows;
    const visible=preview?rows.slice(0,4):items.slice(selection.page*25,(selection.page+1)*25);
    const content=!preview&&selection.barcode?`<div class='product-heading'><div><h3>${esc(row?.name||'Produit identifié')}</h3><p>Référence ${esc(selection.barcode)} · ${row?.count}/${row?.total} boîtes exploitables de ce produit (${number(row?.percent)} %).</p></div><button data-orientation-back data-orientation-kind='${kind}'>Retour aux références</button></div><div class='orientation-proofs'>${visible.map(sample=>sampleHtml(sample,state.connected,'',state.tolerances)).join('')}</div>`:`<div class='table-wrap'><table><thead><tr><th>Produit / référence</th><th>Boîtes concernées</th><th>Part de ce produit</th></tr></thead><tbody>${visible.map(row=>`<tr><td><strong>${esc(row.name||'Produit identifié')}</strong>${preview&&data.orientation_categories?.length?`<small class='orientation-tag'>${esc(data.orientation_categories.find(item=>item.id===row.orientation_category)?.label||'À confirmer')}</small>`:''}<br><button class='reference-link' data-orientation-kind='${preview?(row.orientation_category||kind):kind}' data-orientation-barcode='${esc(row.barcode)}'>${esc(row.barcode)}</button>${row.variant_count>1?'<p class=variant-note>Plusieurs variantes BdD ; comparaison propre à chaque boîte.</p>':''}</td><td>${row.count} sur ${row.total}</td><td>${number(row.percent)} %</td></tr>`).join('')}</tbody></table></div>`;
    if(!items.length)return '<p>Aucune boîte concernée avec les trois sources de mesure disponibles.</p>';
    if(preview)return content;
    return content+`<div class='pagination'><button class='small' data-orientation-kind='${kind}' data-orientation-page='${selection.page-1}' ${selection.page===0?'disabled':''}>Précédents</button><span>Page ${selection.page+1}/${Math.ceil(items.length/25)} · ${items.length} ${selection.barcode?'boîtes':'produits'}</span><button class='small' data-orientation-kind='${kind}' data-orientation-page='${selection.page+1}' ${(selection.page+1)*25>=items.length?'disabled':''}>Suivants</button></div>`;
  }
  function orientationHtml(data,state) {
    if(!data.orientation_references)return '';
    if(data.orientation_categories?.length)return categorizedOrientationHtml(data,state);
    const probable=data.orientation_references.probable||[],uncertain=data.orientation_references.uncertain||[];
    const count=rows=>rows.reduce((sum,row)=>sum+row.count,0);
    return `<section class='section orientations'><h2>Boîtes dans le mauvais sens</h2><p><strong>Orientation probable d’après les dimensions</strong> · ${count(probable)} boîtes, ${probable.length} produits distincts.</p><p class='muted'>Le sens physique reste à vérifier. Cliquer sur une référence rejoint sa première boîte concernée après les trois mesures.</p><div class='orientation-preview'>${orientationRowsHtml(data,state,'probable',true)}</div><details class='orientation-all' data-open='orientation-all'><summary>Voir le détail et toutes les références (${probable.length})</summary><p class='muted'>Une permutation des dimensions BdD explique mieux les trois mesures. Toutes les références sont conservées, même les cas rares ; ces boîtes restent exclues des défauts de mesure. Chaque proportion porte sur les cycles exploitables du produit avant exclusion des orientations.</p><div data-orientation-list='probable'>${orientationRowsHtml(data,state,'probable')}</div></details><details class='orientation-uncertain' data-open='orientation-uncertain'><summary>Orientations indécidables · ${count(uncertain)} boîtes, ${uncertain.length} produits distincts</summary><p>Le sens normal et une autre orientation obtiennent le même score. Ces cas sont exclus du bilan de mesure, sans être classés comme des boîtes dans le mauvais sens.</p><div data-orientation-list='uncertain'>${orientationRowsHtml(data,state,'uncertain')}</div></details></section>`;
  }
  function categorizedOrientationHtml(data,state) {
    const categories=data.orientation_categories,refs=data.orientation_references;
    const rows=categories.flatMap(category=>refs[category.id]||[]).sort((a,b)=>b.count-a.count||b.percent-a.percent||a.orientation_category.localeCompare(b.orientation_category)||a.barcode.localeCompare(b.barcode));
    const count=items=>items.reduce((sum,row)=>sum+row.count,0);
    const blocks=categories.map(category=>{
      const items=refs[category.id]||[];
      return `<details class='orientation-category' data-orientation-category='${esc(category.id)}' data-open='orientation-category-${esc(category.id)}'><summary><strong>${esc(category.label)}</strong><span>${count(items)} boîtes · ${items.length} références</span></summary><p>${esc(category.hypothesis)}</p><div class='orientation-checks'><h4>Contrôles conseillés</h4>${list(category.checks)}</div><div data-orientation-list='${esc(category.id)}'>${orientationRowsHtml(data,state,category.id)}</div></details>`;
    }).join('');
    const uncertain=refs.uncertain||[];
    return `<section class='section orientations'><h2>Boîtes dans le mauvais sens</h2><p><strong>Orientation probable d’après les dimensions</strong> · ${count(rows)} boîtes, ${new Set(rows.map(row=>row.barcode)).size} produits distincts.</p><p class='muted'>Chaque boîte appartient à une seule catégorie. Le sens physique et le moment d’un éventuel retournement restent à confirmer.</p><div class='orientation-preview'>${orientationRowsHtml(data,state,'probable',true,rows)}</div>${blocks}<details class='orientation-uncertain' data-orientation-category='uncertain' data-open='orientation-uncertain'><summary>Orientations indécidables · ${count(uncertain)} boîtes, ${uncertain.length} produits distincts</summary><p>Le sens normal et une autre orientation obtiennent le même score. Ces cas restent séparés des orientations probables.</p><div data-orientation-list='uncertain'>${orientationRowsHtml(data,state,'uncertain')}</div></details><p class='muted'>Les proportions portent sur les cycles exploitables de chaque produit avant exclusion des orientations. Toutes les références sont conservées ; ces boîtes restent exclues des défauts de mesure.</p></section>`;
  }
  function cameraHtml(camera, open=false, groups=[]) {
    if(!camera?.available)return '';
    const max=Math.max(1,...(camera.chart||[]).map(row=>row.success_count));
    return `<details class='section camera-panel' data-open='camera' ${open?'open':''}><summary>Lecture des caméras${groups.some(group=>group.code==='CAMERA_CODE_MODE')?` <span class='camera-mode-alert' title='À paramétrer — mode 123 observé : DataMatrix et codes-barres autorisés' aria-label='Paramétrage caméra à vérifier : mode 123 observé'>⚠</span>`:''}</summary><p class='muted camera-note'>${esc(camera.note)}</p>${(camera.chart||[]).map(row=>`<div class='camera-row'><div class='camera-row-heading'><span>${esc(row.label)}</span><strong>${integer(row.success_count)}</strong></div><div class='bar'><i class='${row.status==='zero'?'zero':''}' style='width:${100*row.success_count/max}%'></i></div><p class='muted'>${esc(row.status_label)}</p></div>`).join('')}<div class='camera-readers'>${(camera.reader_stats||[]).map(row=>`<section><div class='camera-row-heading'><strong>${esc(row.reader)}</strong><span>${integer(row.boxes)} boîtes</span></div><p><b>0 code :</b> ${esc(row.zero_code_label)}</p><small>Caméras ${esc(row.expected_cameras)}</small></section>`).join('')}</div></details>`;
  }
  function robotGroupHtml(group,state) {
    const metrics=group.metrics||{};
    const days=group.daily||[{label:'Dates indisponibles',count:group.occurrence_count,example_start:0,example_count:Math.min(10,(group.examples||[]).length)}];
    const daily=days.map((day,index)=>{
      if(day.observed===false)return `<p class='robot-zero-day'>${esc(day.label)} <span>Période non couverte</span></p>`;
      if(!day.count&&!day.robot_picked_boxes_count&&!day.rejected_boxes_count)return `<p class='robot-zero-day'>${esc(day.label)} <span>Aucune demande</span></p>`;
      const samples=(group.examples||[]).slice(day.example_start,day.example_start+day.example_count);
      const picks=(group.pick_examples||[]).filter(sample=>sample.date===day.date).slice(0,10);
      const boxCounts=metrics.box_metrics_version?`${integer(day.rejected_boxes_count||0)} boîte(s) évacuée(s) · ${integer(day.robot_picked_boxes_count||0)} prise(s) confirmée(s)`:'Données indisponibles — régénérer le rapport';
      return `<details class='robot-day' data-open='robot-day-${esc(group.id)}-${index}'><summary><strong>${esc(day.label)}</strong><span>${integer(day.count)} demande${day.count>1?'s':''}</span></summary><p class='robot-box-counts'>${esc(boxCounts)}</p><p class='muted'>${day.first_time?`De ${esc(day.first_time)} à ${esc(day.last_time)} · `:''}${integer(samples.length)} exemple(s) de demande présenté(s)</p>${samples.map(sample=>sampleHtml(sample,state.connected,'',state.tolerances)).join('')}${picks.length?`<details><summary>Prises confirmées : ${picks.length} preuve(s)</summary>${picks.map(sample=>sampleHtml(sample,state.connected,'',state.tolerances)).join('')}</details>`:''}</details>`;
    }).join('');
    return `<details class='group ${severity(group)}' data-group='${esc(group.id)}' data-open='${esc(group.id)}' ${state.open.has(group.id)?'open':''}><summary><div><div class='badges'><span class='badge ${severity(group)}'>${esc(severityLabel(group))}</span><span class='badge'>Robot/vidage</span></div><h3>${esc(group.title)}</h3><p class='robot-total'>${esc(group.summary)}</p><p class='robot-box-counts'>${esc(group.box_summary||'Données indisponibles — régénérer le rapport')}</p><p class='muted'>${esc(group.trace_period||'Dates indisponibles ; rechargez la trace.')}</p></div></summary><div class='group-body'><p>${esc(group.compact_box_summary||'')}</p><p class='muted'>${esc(group.ratio_explanation||'')}</p>${metrics.requests_start?`<p>Demandes observées du ${esc(metrics.requests_start)} au ${esc(metrics.requests_end)}.</p>`:''}<p class='muted'>${integer(group.displayed_example_count ?? group.examples.length)} exemples présentés sur ${integer(group.evidence_total ?? group.examples.length)} preuves, sur toute la période.</p><h3>Répartition par jour</h3><div class='robot-days'>${daily}</div><p>${esc(group.symptom)}</p><div class='columns'><section><h3>Causes possibles</h3>${list(group.probable_causes)}</section><section><h3>Contrôles conseillés</h3>${list(group.checks)}</section></div></div></details>`;
  }
  function groupHtml(group,state) {
    if(group.code==='DemVidageComplet')return robotGroupHtml(group,state);
    if(['diffT4','MOTOR_COMM'].includes(group.code))return compactGroupHtml(group,state);
    const examples=group.examples||[],page=state.pages[group.id];
    const selected=page==null?examples.filter(s=>(group.representative_ids||[]).includes(s.id)):examples.slice(page*25,page*25+25);
    const pagination=examples.length>3?`<div class="pagination">${page==null?`<button data-page-group="${esc(group.id)}" data-page="0">Voir les ${examples.length} exemples</button>`:`<button data-page-group="${esc(group.id)}" data-page="${Math.max(0,page-1)}" ${page===0?'disabled':''}>Précédents</button><span>Page ${page+1} / ${Math.ceil(examples.length/25)}</span><button data-page-group="${esc(group.id)}" data-page="${page+1}" ${(page+1)*25>=examples.length?'disabled':''}>Suivants</button>`}</div>`:'';
    return `<details class="group ${severity(group)}" data-group="${esc(group.id)}" data-open="${esc(group.id)}" ${state.open.has(group.id)?'open':''}><summary><div><div class="badges"><span class="badge ${severity(group)}">${severityLabel(group)}</span><span class="badge">${esc(group.field_zone_label || group.family_label)}</span><span class="badge">${esc(group.code)}</span></div><h3>${esc(group.title)}</h3><p class="plain-explanation">${esc(group.field_explanation || group.impact || group.symptom)}</p><p>${esc(group.affected_label || group.metric)} · ${esc(action(group))}</p><p class="muted">${esc(group.evidence)}</p>${groupRecurrenceHtml(group)}</div></summary><div class="group-body"><section><h3>Constat et chiffres</h3><p>${esc(group.field_explanation || group.field_impact || group.impact)}</p><p>${esc(group.symptom)}</p>${list(group.business_lines)}<p class="muted">${group.incident_count} diagnostics · Confiance : ${esc(group.confidence)}</p>${Object.keys(group.measurement_stats || {}).length?'<p class="muted">Les compteurs, plages et pistes de mesure figurent dans le bilan en haut du rapport.</p>':''}</section><div class="columns"><section><h3>Causes possibles</h3>${list(group.probable_causes)}</section><section><h3>Contrôles conseillés</h3>${list(group.checks)}</section></div><section class="evidence"><h3>Exemples réels <span class="muted">${integer(group.displayed_example_count ?? examples.length)} exemples présentés sur ${integer(group.evidence_total ?? examples.length)} preuves</span></h3>${group.code==='DemVidageComplet'?robotDaysHtml(group,state):group.series?seriesHtml(group,state):selected.map(sample=>sampleHtml(sample,state.connected,'',state.tolerances)).join('') || '<p class="muted">Aucun exemple individuel disponible.</p>'}${group.series?'':pagination}</section><details><summary>Détail des diagnostics illustrés</summary>${(group.incidents||[]).map(item=>`<article class="sample"><strong>${esc(item.start_time_str)} → ${esc(item.end_time_str)} · L.${item.first_line} à L.${item.last_line}</strong><p>${esc(item.title)} · ${item.count} occurrence(s) · ${esc(item.duration)}</p><p>${esc(item.summary)}</p><p>${esc(item.symptom)}</p><p class="muted">Confiance : ${esc(item.confidence)}</p>${list(item.probable_causes)}${list(item.checks)}</article>`).join('')}</details></div></details>`;
  }
  function compactGroupHtml(group,state) {
    const level=severity(group);
    return `<details class='group ${level}' data-group='${esc(group.id)}' data-open='${esc(group.id)}' ${state.open.has(group.id)?'open':''}><summary><div><div class='badges'><span class='badge ${level}'>${severityLabel(group)}</span><span class='badge'>${esc(group.field_zone_label||group.family_label)}</span></div><h3>${esc(group.title)}</h3><p>${esc(group.metric)}</p><p class='muted'>Observations : ${esc(group.start_time_str)} → ${esc(group.end_time_str)}</p></div></summary><div class='group-body'><p>${esc(group.symptom)}</p><p><strong>Premier contrôle</strong><br>${esc(action(group))}</p>${group.code==='diffT4'?`<p class='muted'>${esc(group.checks?.[1])}</p>`:''}<details><summary>Causes et contrôles complémentaires</summary>${list(group.probable_causes)}${list((group.checks||[]).slice(1))}</details><section class='evidence'><h3>${group.code==='diffT4'?'Observations par fichier':'Interruptions critiques'}</h3><p class='muted'>${integer(group.displayed_example_count ?? group.examples.length)} exemples présentés sur ${integer(group.evidence_total ?? group.examples.length)} preuves.</p>${seriesHtml(group,state)}</section></div></details>`;
  }
  function identityText(identity) {
    if(!identity?.pharmacy || !identity.alpha_database || !identity.pharmacy_database)return '';
    return `Pharmacie ${identity.pharmacy} · ${identity.alpha_number?`Alpha ${identity.alpha_number}`:identity.alpha_database}`;
  }
  function identityHtml(identity) {
    if(!identityText(identity))return '';
    return `<div class='hero-identity'><span class='pharmacy-name'><svg aria-hidden='true' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.7'><path d='M9 3h6v6h6v6h-6v6H9v-6H3V9h6z'/></svg>${esc(`Pharmacie ${identity.pharmacy}`)}</span><span class='alpha-identity'>${esc(identity.alpha_number?`Alpha ${identity.alpha_number}`:identity.alpha_database)}</span></div>`;
  }
  /* Le PDF utilise les chiffres complets mais seulement les reperes terrain. */
  function pdfLines(data) {
    const result=[],handled=new Set(),groups=data.groups||[],axes=['length','width','height'];
    const add=(text,kind='text',extra={})=>result.push({text:String(text??''),kind,...extra});
    const table=(headers,rows,widths)=>result.push({kind:'table',headers,rows,widths});
    const page=(title,subtitle)=>add(title,'page',{subtitle});
    const metric=group=>{
      const m=group.metrics||{};
      if(group.code==='DemVidageComplet')return [group.summary,group.compact_box_summary||group.box_summary].filter(Boolean).join(' · ');
      if(group.code==='T5_STALE_UNMEASURED_BOX')return group.priority_impact?.available?group.priority_impact.cycles+' cycles de boîtes bloquants · '+group.priority_impact.episodes+' épisodes observés':'Impact indisponible — régénérer le rapport';
      if(group.code==='C5_SIGNAL_ANOMALY'&&m.c5_metrics_version)return m.suspect_cycle_count+' boîtes fantômes probables · '+m.episode_count+' épisodes C5 · '+m.virtual_creation_count+' créations virtuelles explicites';
      if(group.code==='DP_MISSING'&&m.observation_metrics_version)return m.confirmed_count+' boîtes sans DP · '+m.recovered_count+' récupérées en relecture'+(m.unattributed_signal_count?' · '+m.unattributed_signal_count+' signalements non attribuables':'');
      if(group.code==='CAMERA_CODE_MODE'&&(m.readers||m.episodes))return [...new Set((m.readers || m.episodes.map(row=>row.reader)))].sort().join(' et ')+' en mode 123 : DataMatrix et codes-barres autorisés';
      return group.affected_label||group.metric||'';
    };
    const card=group=>{
      handled.add(group.id);
      add(group.title,'card',{level:severity(group),label:severityLabel(group),
        metric:group.code==='DemVidageComplet'?[group.summary,group.compact_box_summary].filter(Boolean).join(' · '):metric(group),
        body:group.symptom||group.impact||'',action:action(group)});
    };
    page('Synthèse terrain','Les points essentiels pour préparer le contrôle de l’Alpha');
    add(identityText(data.source?.identity)||data.source?.name||'Trace analysée','identity');
    add(sourcePeriodText(data.source),'note');
    add((data.source?.files?.length||1)+' fichier(s) analysé(s) · '+(data.source?.duration||'Durée indisponible'),'note');
    if(data.source?.gaps?.length)add(data.source.gaps.length+' période(s) non couverte(s) : une absence de trace ne prouve pas un fonctionnement normal.','note');
    add('','kpis',{values:[
      [integer(data.counts?.analyzed_boxes),'boîtes observées','neutral'],
      [integer(data.counts?.error),'types de problèmes critiques','error'],
      [integer(data.counts?.warning),'types de problèmes en alerte','warning'],
      [data.unknown?.total?number(100*data.unknown.count/data.unknown.total)+' %':'Indisponible','UNKNOWN CB1+CB2 · '+integer(data.unknown?.count)+' / '+integer(data.unknown?.total),'neutral']
    ]});
    add('À vérifier en premier','section');
    const priorities=(data.priority||[]).slice(0,3);
    for(const group of priorities)card(group);
    if(!priorities.length)add('Aucun problème prioritaire détecté.','note');

    page('Mesures et présentation','Comparaison avec le produit identifié en base, sans les orientations indécidables');
    add(globalMeasurementText(data.measurements||{}),'note');
    add(measurementTotal(data.measurements||{}),'note');
    add(thresholdText(data.measurements),'note');
    table(['Dimension','Hors tolérance / comparables','En moins / en trop'],axes.filter(name=>data.measurements?.axes?.[name]).map(name=>{
      const axis=data.measurements.axes[name];
      return [axisInfo[name].label,integer(axis.anomalies.count)+' / '+integer(axis.all.count)+' · '+(axis.all.count?number(axis.all.outside_percent)+' %':'indisponible'),integer(axis.anomalies.under_count)+' / '+integer(axis.anomalies.over_count)];
    }),[105,230,180]);
    add('Produits à contrôler en priorité','section');
    const products=[];
    for(const name of axes){
      const rows=['under','over'].flatMap(side=>primaryRows(data,name,side).map(row=>({...row,side})));
      rows.sort((a,b)=>b.count-a.count||Math.abs(b.worst)-Math.abs(a.worst)||String(a.barcode).localeCompare(String(b.barcode)));
      for(const row of rows.slice(0,2))products.push([axisInfo[name].label+' '+(row.side==='under'?'−':'+'),(row.name||'Produit identifié')+' · '+row.barcode,row.count+'/'+row.total+' · '+signed(row.worst)+' mm']);
    }
    if(products.length)table(['Axe / sens','Produit / CIP','Boîtes · pire écart'],products,[90,305,120]);
    else add('Aucun produit avec au moins 10 % de défauts par côté. Les cas rares restent inclus dans les totaux.','note');
    add('Deux produits maximum par dimension, classés par effectif puis écart ; les cas rares restent inclus dans les totaux. Listes complètes dans le web.','note');
    const categories=data.orientation_categories?.length?[...data.orientation_categories,{id:'uncertain',label:'Orientations indécidables'}]:[{id:'probable',label:'Orientations probables'},{id:'uncertain',label:'Orientations indécidables'}];
    const orientations=categories.map(category=>{
      const rows=data.orientation_references?.[category.id]||[],first=rows[0];
      return [category.label,rows.reduce((sum,row)=>sum+row.count,0),first?first.barcode+' · '+first.count+'/'+first.total:''];
    }).filter(([,count])=>count);
    if(orientations.length){
      add('Présentation des boîtes','section');
      table(['Constat','Cycles','Produit principal / exploitables'],orientations.map(([label,count,product])=>[label,String(count),product]),[230,65,220]);
      add('Sens physique à vérifier. Catégories non additives ; ces cycles sont exclus du bilan de réglage.','note');
      if((data.orientation_references?.on_edge||[]).length)add('Sur tranche : vérifier la présentation bien à plat et la hauteur de restitution du robot.','note');
    }
    const excluded=Object.entries(data.measurements?.excluded||{}).filter(([,count])=>count);
    if(excluded.length)add('Non comparées : '+excluded.map(([key,count])=>count+' '+(exclusionLabels[key]||key)).join(' · '),'note');
    const examples=[];
    for(const name of axes){
      const row=['under','over'].flatMap(side=>primaryRows(data,name,side)).sort((a,b)=>b.count-a.count||Math.abs(b.worst)-Math.abs(a.worst))[0];
      const sample=(data.measurement_examples||[]).find(sample=>sample.id===row?.navigation_sample_id||sample.id===row?.sample_ids?.[0]);
      if(sample&&!examples.some(item=>item.id===sample.id))examples.push({...sample,axis:name});
    }
    if(examples.length){
      const rows=[];
      for(const sample of examples.slice(0,3)){
        const index={length:2,width:0,height:1}[sample.axis];
        rows.push(axisInfo[sample.axis].label+' · '+sample.barcode+' · '+sample.measured[index]+' mm mesurés / '+sample.expected[index]+' mm attendus · écart '+signed(sample.deltas[index])+' mm.');
      }
      result.push({kind:'examples',rows});
    }
    groups.filter(group=>({T4_LENGTH:['length'],T5_WIDTH:['width'],T5_HEIGHT:['height'],GLOBAL:axes}[group.code]||[]).some(name=>data.measurements?.axes?.[name]?.all?.count)||group.code==='ORIENTATION'&&orientations.length).forEach(group=>handled.add(group.id));

    page('Lecture et exploitation','Identification des produits, sorties robot et communication des tapis');
    if(data.camera?.available){
      add('Lecture des caméras'+(groups.some(group=>group.code==='CAMERA_CODE_MODE')?' — À paramétrer':''),'section');
      table(['Caméra / lecteur','Lectures contributives'],(data.camera.chart||[]).map(row=>[row.label,integer(row.success_count)]),[365,150]);
      table(['Lecteur','Passages observés','Lectures à 0 code'],(data.camera.reader_stats||[]).map(row=>[row.reader,integer(row.boxes),row.zero_code_label]),[85,145,285]);
      add('Une boîte peut contribuer à plusieurs caméras : ne pas additionner ces lectures comme des boîtes distinctes.','note');
    }
    const operational=['UNKNOWN','CAM-NO-READ','DP_MISSING','CAMERA_CODE_MODE','DemVidageComplet','MOTOR_COMM','REFERENCE_ABSENT','REFERENCE_NON_ALPHATISABLE'];
    const operations=groups.filter(group=>operational.includes(group.code));
    if(operations.length)table(['Niveau','Constat','Premier contrôle'],operations.map(group=>{
      const shown=handled.has(group.id);handled.add(group.id);
      return [severityLabel(group),group.title+(shown?'':'\n'+metric(group)),shown?'Voir la priorité en première page.':action(group)];
    }),[65,270,180]);
    add('Prises robot confirmées : hors vidages. Part évacuée = évacuées / (prises confirmées + évacuées).','note');

    const others=groups.filter(group=>!handled.has(group.id)&&severity(group)!=='info');
    if(others.length){
      page('Autres problèmes et actions','Un constat par type de problème ; preuves et sources dans le rapport web');
      table(['Niveau','Constat et effectif','Premier contrôle'],others.map(group=>[severityLabel(group),group.title+'\n'+metric(group)+'\n'+(group.symptom||group.impact||''),action(group)]),[65,270,180]);
    }
    const infos=groups.filter(group=>severity(group)==='info'&&!handled.has(group.id));
    if(infos.length)add(infos.length+' type(s) d’information complémentaire(s) dans le rapport web.','note');
    add('Fichiers, dates et preuves : consulter le rapport web. Les causes et réglages proposés restent à confirmer sur la machine.','note');
    return result;
  }

  /* Mise en page vectorielle locale : cartes indivisibles et tableaux pagines. */
  function buildPdf(data) {
    const encode=value=>String(value??'').replace(/→/g,'>').replace(/[−–—]/g,'-').replace(/’/g,"'").replace(/œ/g,'oe').replace(/\u202f|\u00a0/g,' ').replace(/[^\x20-\x7e\xa0-\xff\n]/g,' ');
    const escape=value=>encode(value).replace(/\\/g,'\\\\').replace(/\(/g,'\\(').replace(/\)/g,'\\)');
    const palette={ink:[.10,.17,.26],muted:[.34,.41,.48],blue:[.10,.31,.49],line:[.84,.89,.93],error:[.72,.14,.21],warning:[.63,.38,.04],neutral:[.10,.31,.49]};
    const pale={error:[1,.95,.95],warning:[1,.97,.90],neutral:[.94,.97,1]};
    const rgb=(color,stroke=false)=>color.join(' ')+(stroke?' RG\n':' rg\n');
    const canvas=typeof document!=='undefined'?document.createElement('canvas').getContext('2d'):null;
    const width=(value,size,bold=false)=>{
      if(canvas){canvas.font=(bold?'bold ':'')+size+'px Arial';return canvas.measureText(encode(value)).width;}
      return encode(value).length*size*.53;
    };
    const wrap=(value,max,size=10,bold=false)=>{
      const lines=[];
      for(const paragraph of encode(value).split('\n')){
        let line='';
        for(let word of paragraph.split(/\s+/).filter(Boolean)){
          while(width(word,size,bold)>max){
            if(line){lines.push(line);line='';}
            let count=1;while(count<word.length&&width(word.slice(0,count+1),size,bold)<=max)count++;
            lines.push(word.slice(0,count));word=word.slice(count);
          }
          if(width((line+' '+word).trim(),size,bold)>max){lines.push(line);line=word;}
          else line=(line+' '+word).trim();
        }
        if(line)lines.push(line);
      }
      return lines.length?lines:[''];
    };
    const pages=[];let body='',y=746,currentTitle='',currentSubtitle='';
    const text=(value,x,top,size=10,bold=false,color=palette.ink)=>{
      body+=rgb(color)+'BT /'+(bold?'F2':'F1')+' '+size+' Tf '+x+' '+(top-size)+' Td ('+escape(value)+') Tj ET\n';
    };
    const rect=(x,top,w,h,color)=>{body+=rgb(color)+x+' '+(top-h)+' '+w+' '+h+' re f\n';};
    const rule=top=>{body+=rgb(palette.line,true)+'38 '+top+' m 557 '+top+' l S\n';};
    const paragraph=(value,x,top,max,size=10,bold=false,color=palette.ink)=>{
      const lines=wrap(value,max,size,bold);lines.forEach((line,index)=>text(line,x,top-index*(size+4),size,bold,color));
      return lines.length*(size+4);
    };
    const end=()=>{if(body)pages.push(body);body='';};
    const begin=(title,subtitle,continuation=false)=>{
      end();currentTitle=title;currentSubtitle=subtitle;
      rect(0,842,595,8,palette.blue);text('TRACEALPHAVIEWER',38,816,9,true,palette.blue);
      const pharmacy=identityText(data.source?.identity);
      if(pharmacy)wrap(pharmacy,257,8).slice(0,2).forEach((line,index)=>text(line,300,816-index*12,8,false,palette.muted));
      text(title+(continuation?' · suite':''),38,786,22,true);
      const h=subtitle?paragraph(subtitle,38,753,519,10,false,palette.muted):0;
      y=753-h-14;rule(y+3);
    };
    const ensure=height=>{if(y-height<56)begin(currentTitle,currentSubtitle,true);};
    const note=(value,kind='note')=>{
      const size=kind==='identity'?17:kind==='example'?9:10,bold=kind==='identity';
      const lines=wrap(value,kind==='example'?495:519,size,bold),h=lines.length*(size+4)+6;
      ensure(h);if(kind==='example')rect(38,y+3,519,h,pale.neutral);
      paragraph(value,kind==='example'?50:38,y,kind==='example'?495:519,size,bold,kind==='identity'?palette.ink:palette.muted);y-=h;
    };
    for(const item of pdfLines(data)){
      if(item.kind==='page'){begin(item.text,item.subtitle);continue;}
      if(item.kind==='examples'){
        // Les reperes facultatifs ne creent jamais une page presque vide.
        const heights=item.rows.map(value=>wrap(value,495,9).length*13+6);
        if(y-23-heights[0]<56)continue;
        text('Repères représentatifs',38,y,13,true,palette.blue);y-=23;
        for(let index=0;index<item.rows.length;index++){
          if(y-heights[index]<56)break;
          note(item.rows[index],'example');
        }
        continue;
      }
      if(item.kind==='kpis'){
        ensure(114);
        item.values.forEach(([value,label,tone],index)=>{
          const x=38+(index%2)*265,top=y-Math.floor(index/2)*58;
          rect(x,top,254,50,pale[tone]);text(value,x+12,top-6,20,true,palette[tone]);text(label,x+12,top-31,9,false,palette.muted);
        });y-=124;continue;
      }
      if(item.kind==='section'){ensure(65);text(item.text,38,y,13,true,palette.blue);y-=23;continue;}
      if(item.kind==='card'){
        const titleLines=wrap(item.text,485,12,true),metricLines=wrap(item.metric,485,11,true),bodyLines=wrap(item.body,485,10),actionLines=wrap('Premier contrôle : '+item.action,485,10);
        const height=29+titleLines.length*16+metricLines.length*15+bodyLines.length*14+actionLines.length*14+22;
        ensure(height);rect(38,y,519,height,pale[item.level]||pale.neutral);rect(38,y,3,height,palette[item.level]||palette.blue);
        let top=y-10;text(item.label.toUpperCase(),52,top,8,true,palette[item.level]||palette.blue);top-=17;
        top-=paragraph(item.text,52,top,485,12,true)+5;
        top-=paragraph(item.metric,52,top,485,11,true)+5;
        top-=paragraph(item.body,52,top,485,10,false,palette.muted)+7;
        paragraph('Premier contrôle : '+item.action,52,top,485,10);y-=height+12;continue;
      }
      if(item.kind==='table'){
        if(!item.rows.length)continue;
        const widths=item.widths||item.headers.map(()=>515/item.headers.length),size=9;
        const rowHeight=row=>Math.max(...row.map((cell,index)=>wrap(cell,widths[index]-18,size).length))*13+12;
        const drawRow=(row,header=false,index=0)=>{
          const height=rowHeight(row);
          if(header)rect(38,y,515,height,[.89,.94,.98]);else if(index%2===0)rect(38,y,515,height,[.97,.98,.99]);
          let x=38;row.forEach((cell,index)=>{paragraph(cell,x+9,y-5,widths[index]-18,size,header,header?palette.blue:palette.ink);x+=widths[index];});
          y-=height;rule(y);
        };
        ensure(rowHeight(item.headers)+rowHeight(item.rows[0]));drawRow(item.headers,true);
        for(let index=0;index<item.rows.length;index++){
          const row=item.rows[index],height=rowHeight(row);
          if(y-height<56){begin(currentTitle,currentSubtitle,true);drawRow(item.headers,true);}
          drawRow(row,false,index);
        }
        y-=14;continue;
      }
      note(item.text,item.kind);
    }
    end();
    const objects=[],add=value=>(objects.push(value),objects.length);
    const f1=add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'),f2=add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>'),ids=[];
    pages.forEach((page,index)=>{
      body=page;rule(43);text('Analyse locale · '+String(data.generated_at||''),38,33,8,false,palette.muted);text((index+1)+' / '+pages.length,514,33,8,false,palette.muted);
      const stream=add('<< /Length '+body.length+' >>\nstream\n'+body+'endstream');
      ids.push(add('<< /Type /Page /Parent PARENT 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 '+f1+' 0 R /F2 '+f2+' 0 R >> >> /Contents '+stream+' 0 R >>'));
    });
    const parent=add('<< /Type /Pages /Kids ['+ids.map(id=>id+' 0 R').join(' ')+'] /Count '+ids.length+' >>'),catalog=add('<< /Type /Catalog /Pages '+parent+' 0 R >>');
    for(const id of ids)objects[id-1]=objects[id-1].replace('PARENT',parent);
    let pdf='%PDF-1.4\n';const offsets=[0];objects.forEach((object,index)=>{offsets.push(pdf.length);pdf+=(index+1)+' 0 obj\n'+object+'\nendobj\n';});
    const offset=pdf.length;pdf+='xref\n0 '+(objects.length+1)+'\n0000000000 65535 f \n';offsets.slice(1).forEach(value=>pdf+=String(value).padStart(10,'0')+' 00000 n \n');
    pdf+='trailer\n<< /Size '+(objects.length+1)+' /Root '+catalog+' 0 R >>\nstartxref\n'+offset+'\n%%EOF';
    return Uint8Array.from(pdf,c=>c.charCodeAt(0));
  }
  function downloadPdf(data) {
    const blob=new Blob([buildPdf(data)],{type:'application/pdf'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='diagnostic-terrain.pdf';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  scope.TraceReport={mount,buildPdf,pdfLines};
})(globalThis);
