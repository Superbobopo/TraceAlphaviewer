"""Episodes de communication et modes de lecture observes, sans dependance Tk."""
import re
from Models.robot_drain import TraceCalendar
from Models.trace_calendar import trace_calendar, display_time, format_observed_time

OBSERVATION_CODES = {'MOTOR_COMM', 'DP_MISSING', 'CAMERA_CODE_MODE'}


def observation_metric_text(code, metrics):
    if code=='MOTOR_COMM':
        count=metrics['critical_episode_count']
        parts=[f"{count} interruption{'s' if count!=1 else ''} avec défaut de communication"]
        for key,label in (('recovered_episode_count','avec échanges rétablis'),
                          ('reconnected_episode_count','avec socket reconnecté seulement'),
                          ('unresolved_episode_count','sans reprise observée')):
            if metrics.get(key):parts.append(f"{metrics[key]} {label}")
        return ' · '.join(parts)
    if code=='DP_MISSING':
        return (f"{metrics['confirmed_count']} boîte(s) sans DP après identification · "
                f"{metrics['recovered_count']} récupérée(s) par relecture · "
                f"{metrics['unattributed_signal_count']} signalement(s) non attribuable(s)")
    return (f"{metrics['episode_count']} période(s) en mode 123 · "
            f"{metrics['request_count']} demande(s) de décodage · DataMatrix seul attendu (mode 1)")


def observation_is_priority(group):
    return not (group['code'] in {'MOTOR_COMM','DP_MISSING'} and group['severity']=='info')
_RETRY = re.compile(r"envoi cde vers StepMotors pour le (\d+)\S* essai.*?cde:'([^']+)'", re.I)
_OK = re.compile(r"Comm\.\s*OK sur StepMotors.*?cde:'([^']+)'", re.I)
_COMMAND = re.compile(r"cde:'([^']+)'", re.I)
_FAULT = re.compile(r'DEFAUT de Comm\. StepMotors|Erreur winsock \(StepMotors\)|(?:port.*non ouvert.*StepMotors|Port StepMotors NON OUVERT)|028-Avt:.*communication carte moteurs', re.I)
_CONNECT = re.compile(r'Connexion socket .*?StepMotors.*?\.Ok', re.I)
_STOP = re.compile(r'version logiciel VBalpha:|ferme TCPIP\(0\) StepMotors', re.I)
_INIT = re.compile(r'InitMachine: demande initialisation de (T[0-5])\b', re.I)
_MODE = re.compile(r'idCB([12]):.*?codes autoris\S*s:(\d+)\b', re.I)


def observations(line_states, origin=None, *, wanted=None, format_if=None):
    dated = TraceCalendar(origin) if origin else None
    calendar = {} if dated else trace_calendar(line_states)
    for line, text, state in line_states:
        moment = dated.at(state.timestamp) if dated else None
        if wanted is not None and line not in wanted:
            continue
        time_str = (format_observed_time(moment) if moment else display_time(calendar,line,state.timestamp_str)) if (
            format_if is None or format_if(text)) else None
        yield text, {'line': line, 'time': (moment-origin).total_seconds() if moment else state.timestamp,
                     'time_str': time_str}


def _episode(first):
    return {'first_line':first['line'],'last_line':first['line'],'start_time':first['time'],
            'end_time':first['time'],'start_time_str':first['time_str'],'end_time_str':first['time_str'],
            'sources':{'début':first['line']}}


def _touch(episode, obs, label=None):
    episode.update(last_line=obs['line'],end_time=obs['time'],end_time_str=obs['time_str'])
    if label and len(episode['sources'])<10:
        episode['sources'][label]=obs['line']


def analyze_motor_communication(line_states, origin=None):
    episodes=[]
    active=recent=None
    pending={}
    last_signal=None

    def close(reason, status='unknown'):
        nonlocal active, recent, pending
        if active:
            active.update(end_reason=reason,status=status,
                          duration_seconds=max(0,active['end_time']-active['start_time']),
                          severity='error' if active['fault_count'] else 'info')
            episodes.append(active)
            recent=active
        active=None
        pending={}

    relevant = re.compile(r'StepMotors|028-Avt:|InitMachine:|version logiciel VBalpha:', re.I)
    for text,obs in observations(line_states,origin,format_if=relevant.search):
        if active and obs['time']-last_signal>120:
            close('Plus de 120 secondes sans nouveau signal ; résolution inconnue')
        if obs['time_str'] is None:
            continue
        if _STOP.search(text):
            close('Arrêt ou redémarrage logiciel ; récupération non attestée')
            recent=None
            continue
        init=_INIT.search(text)
        target=active or (recent if recent and recent.get('reconnection_time') is not None
                         and 0<=obs['time']-recent['reconnection_time']<=2 else None)
        if init and target:
            target['initializations'].append(dict(obs,belt=init[1].upper()))
            if len(target['sources'])<10:target['sources'][f'initialisation {init[1].upper()}']=obs['line']
        retry=_RETRY.search(text)
        fault=_FAULT.search(text)
        ok=_OK.search(text)
        if retry or fault:
            if active is None:
                active=dict(_episode(obs),retry_count=0,fault_count=0,winsock_error_count=0,
                            reconnect_count=0,recovered_commands=0,commands=[],initializations=[])
            _touch(active,obs,'dernier signal')
            last_signal=obs['time']
            command=retry[2] if retry else (_COMMAND.search(text)[1] if _COMMAND.search(text) else '')
            if command:
                pending[command]=obs
                if command not in active['commands']:active['commands'].append(command)
            if retry:active['retry_count']+=1
            if fault:
                active['fault_count']+=1
                if 'winsock' in text.lower():active['winsock_error_count']+=1
                active['sources'].setdefault('premier défaut',obs['line'])
        elif ok and active and ok[1] in pending and 0<=obs['time']-pending[ok[1]]['time']<=120:
            pending.pop(ok[1])
            _touch(active,obs,'échanges rétablis')
            last_signal=obs['time']
            active['recovered_commands']+=1
            if not pending:close('Réponse de communication explicitement rétablie','recovered')
        elif _CONNECT.search(text) and active:
            _touch(active,obs,'socket reconnecté')
            active['reconnect_count']+=1
            active['reconnection_time']=obs['time']
            close('Socket reconnecté ; échanges avec la carte à confirmer','reconnected')
    close('Fin de fichier ; résolution non observée')
    for episode in episodes:
        status=('Critique' if episode['severity']=='error' else
                'Information — réessai récupéré' if episode['status']=='recovered' else 'Information — résultat indéterminé')
        belts=sorted({match for command in episode['commands'] for match in re.findall(r'(T[0-5])(?=\D|$)',command)})
        common=[command for command in episode['commands'] if not re.search(r'T[0-5](?=\D|$)',command)]
        episode['belts']=belts
        episode['common_commands']=common
        episode['detail']=(f"{status} : la carte qui commande les tapis a signalé {episode['fault_count']} défaut(s). "
            f"Commandes concernées : {', '.join(episode['commands']) or 'non précisées'}. "
            f"Tapis identifiables : {', '.join(belts) or 'aucun tapis précis dans ces commandes'}. "
            f"{len(episode['initializations'])} demande(s) d’initialisation consécutive(s). {episode['end_reason']}.")
    return episodes


def analyze_code_modes(line_states, origin=None):
    periods=[]
    active={}
    previous=None

    def close(reader,reason,boundary=None):
        item=active.pop(reader,None)
        if item:
            item.update(end_reason=reason,duration_seconds=max(0,item['end_time']-item['start_time']))
            if boundary:item['sources']['fin du contexte']=boundary['line']
            item['detail']=(f"{reader} : mode 123 observé, DataMatrix et codes-barres autorisés ; "
                f"{item['request_count']} demande(s) de décodage. Vérifier le réglage DataMatrix seul (mode 1). {reason}.")
            periods.append(item)

    relevant = re.compile(r'idCB[12]:|StepMotors|version logiciel VBalpha:', re.I)
    for text,obs in observations(line_states,origin,format_if=relevant.search):
        if previous and obs['time']-previous['time']>120:
            for reader in list(active):close(reader,'Observations interrompues plus de 120 secondes')
        previous=obs
        if obs['time_str'] is None:
            continue
        if _STOP.search(text):
            for reader in list(active):close(reader,'Arrêt ou redémarrage logiciel',obs)
        match=_MODE.search(text)
        if not match:continue
        reader='CB'+match[1]
        if match[2]!='123':
            close(reader,'Mode 1 DataMatrix seul observé' if match[2]=='1' else f'Mode {match[2]} non interprété observé',obs)
            continue
        if reader not in active:active[reader]=dict(_episode(obs),reader=reader,mode='123',request_count=0)
        active[reader]['request_count']+=1
        _touch(active[reader],obs,'dernière demande en mode 123')
    for reader in list(active):close(reader,'Fin de fichier ; changement de mode non observé')
    return sorted(periods,key=lambda row:row['first_line'])
