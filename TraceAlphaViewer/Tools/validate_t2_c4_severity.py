"""Verifie le seuil glissant T2/C4 et sa coherence dans le rapport."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.diagnostic import _build_motor_error_incidents, _t4_repeated_init_incident
from Models.diagnostic_report import build_report_payload
from Models.state import MachineEvent, MachineState


def check_case(times, severity, maximum):
    events = [MachineEvent(index, moment, '12:00:00', 'error', 'ERREUR',
                           'T2 en erreur eT:-88')
              for index, moment in enumerate(times, 1)]
    incident, = _build_motor_error_incidents(events)
    assert incident.count == len(times)
    assert incident.severity == severity
    assert incident.metrics['max_24h_count'] == maximum
    group, = build_report_payload([incident], [])['groups']
    assert group['field_severity'] == severity
    assert group['severity'] == severity


def main():
    for count in (1, 3, 9, 10, 11):
        check_case(list(range(count)), 'error' if count >= 10 else 'warning', count)
    check_case([day * 90000 for day in range(24)], 'warning', 1)
    check_case([0] + list(range(86392, 86401)), 'error', 10)
    check_case([0] + list(range(86393, 86402)), 'warning', 9)
    check_case(list(range(86395, 86405)), 'error', 10)

    sequence = [(index, MachineState(line_num=index, timestamp=index)) for index in range(1, 25)]
    t4 = _t4_repeated_init_incident(sequence, [], [])
    group, = build_report_payload([t4], [])['groups']
    assert t4.count == 24 and t4.severity == 'error'
    assert group['field_severity'] == 'error'

    old = _build_motor_error_incidents([
        MachineEvent(1, 0, '12:00:00', 'error', 'ERREUR', 'T2 en erreur eT:-88')])[0]
    old.metrics = {}
    old.count = 24
    old.severity = 'error'
    group, = build_report_payload([old], [])['groups']
    assert group['field_severity'] == 'warning'
    print('T2/C4 : seuils 24 h, bornes, multi-jours, rapport et regression T4 OK')


if __name__ == '__main__':
    main()
