"""Syntheses terrain communes au viewer, aux dossiers et aux rapports."""
from dataclasses import asdict, replace

T4_TITLE = 'T4 — mesures de longueur incohérentes'
T4_SYMPTOM = 'Deux valeurs internes de longueur, T4C et T4T, ne concordent pas pour ces passages.'
T4_CHECK = 'Vérifier le passage des boîtes devant C6, leur stabilité et un éventuel glissement.'
T4_EXPLANATION = ("Ce contrôle compare deux valeurs internes, pas la longueur attendue en base produits. "
                  "Il ne prouve pas, seul, qu’une boîte est trop longue ou trop courte.")


def t4_metric_text(metrics, count):
    maximum = metrics.get('max_abs_diff_mm')
    text = f'{count} contrôles avec un écart supérieur à 10 mm'
    text += (f' · écart maximal : {maximum} mm' if maximum is not None else
             ' · maximum indisponible — régénérer le rapport')
    affected, total = metrics.get('affected_files'), metrics.get('analyzed_files')
    if affected is not None and total:
        text += f' · {affected} fichier(s) concerné(s) sur {total} analysé(s)'
    return text


def motor_metrics(episodes):
    metrics = {'observation_metrics_version': 2, 'episodes': episodes,
               'episode_count': len(episodes), 'critical_episode_count': len(episodes),
               'recovered_episode_count': sum(row['status'] == 'recovered' for row in episodes),
               'reconnected_episode_count': sum(row['status'] == 'reconnected' for row in episodes),
               'unresolved_episode_count': sum(row['status'] not in {'recovered', 'reconnected'} for row in episodes),
               'initialization_count': sum(len(row['initializations']) for row in episodes)}
    for key in ('retry_count', 'fault_count', 'winsock_error_count', 'reconnect_count'):
        metrics[key] = sum(row[key] for row in episodes)
    return metrics


def normalize_summary_incidents(incidents, analyzed_files=None):
    """Ne modifie pas les incidents d'origine ni les limites des segments."""
    from Models.trace_observations import observation_metric_text
    result, t4 = [], []
    for incident in incidents:
        if incident.code == 'diffT4':
            t4.append(incident)
            continue
        if incident.code == 'MOTOR_COMM':
            episodes = [dict(row) for row in incident.metrics.get('episodes', []) if row.get('severity') == 'error']
            if not episodes:
                # Les anciens resultats critiques sans preuve structuree restent explicites.
                if incident.severity == 'error' and not incident.metrics.get('observation_metrics_version'):
                    result.append(replace(incident, summary='Détails indisponibles — régénérer le rapport'))
                continue
            metrics = motor_metrics(episodes)
            first, last = min(episodes, key=lambda row: row['first_line']), max(episodes, key=lambda row: row['last_line'])
            examples = [dict(line=row['first_line'], time_str=row['start_time_str'],
                             display_time_str=row['start_time_str'], box='', barcode='',
                             detail=row['detail'], sources=dict(list(row['sources'].items())[:10]), episode=index)
                        for index, row in enumerate(episodes, 1)]
            incident = replace(incident, severity='error', count=len(episodes), metrics=metrics,
                first_line=first['first_line'], last_line=last['last_line'], start_time=first['start_time'],
                end_time=last['end_time'], start_time_str=first['start_time_str'], end_time_str=last['end_time_str'],
                summary=observation_metric_text('MOTOR_COMM', metrics), examples=examples,
                event_lines=[row['line'] for row in examples],
                symptom="L’Alpha a signalé un défaut de communication avec la carte qui commande les tapis.")
        result.append(incident)
    if not t4:
        return result
    # Chaque serie conserve ses bornes et ses preuves, meme dans une seule carte.
    segments = [dict(segment, metrics=dict(segment['metrics'],
                    source_segment=incident.metrics.get('source_segment', segment['metrics'].get('source_segment', index))))
                for index, incident in enumerate(t4) for segment in
                (incident.metrics.get('segments') or [asdict(incident)])]
    segments.sort(key=lambda row: row['first_line'])
    maxima = [row['metrics'].get('max_abs_diff_mm') for row in segments]
    source_ids = {row['metrics'].get('source_segment', index) for index, row in enumerate(segments)}
    total = analyzed_files or max((row.metrics.get('analyzed_files', 0) for row in t4), default=0) or len(source_ids)
    metrics = {'t4_diff_metrics_version': 1, 'segments': segments,
               'max_abs_diff_mm': max(maxima) if all(value is not None for value in maxima) else None,
               'affected_files': len(source_ids), 'analyzed_files': total}
    count = sum(row['count'] for row in segments)
    first, last = segments[0], max(segments, key=lambda row: row['last_line'])
    result.append(replace(t4[0], title=T4_TITLE, count=count, metrics=metrics,
        first_line=first['first_line'], last_line=last['last_line'], start_time=first['start_time'],
        end_time=last['end_time'], start_time_str=first['start_time_str'], end_time_str=last['end_time_str'],
        summary=t4_metric_text(metrics, count), symptom=T4_SYMPTOM,
        checks=[T4_CHECK, T4_EXPLANATION],
        event_lines=[line for row in segments for line in row['event_lines']],
        examples=[sample for row in segments for sample in row['examples'][:10]]))
    return result
