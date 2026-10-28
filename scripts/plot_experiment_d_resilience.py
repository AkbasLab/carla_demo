"""Plot a saved Experiment D run without connecting to a model or simulator."""
import argparse
import csv
import json
import math
from pathlib import Path


def recovery_distances(rows, summary):
    """Distances through stable-recovery confirmation; no result for incomplete recovery."""
    detection, recovery = summary.get('failsafe_detection_s'), summary.get('recovery_observed_s')
    if detection is None or recovery is None:
        return dict(recovery_path_length_m=None, recovery_net_displacement_m=None)
    samples = [r for r in rows if detection <= float(r['wall_elapsed_s']) <= recovery]
    if len(samples) < 2 or any(not all(k in r for k in ('x', 'y', 'z')) for r in samples):
        return dict(recovery_path_length_m=None, recovery_net_displacement_m=None)
    points = [tuple(float(r[k]) for k in ('x', 'y', 'z')) for r in samples]
    return dict(recovery_path_length_m=sum(math.dist(a, b) for a, b in zip(points, points[1:])),
                recovery_net_displacement_m=math.dist(points[0], points[-1]))


def generate_plots(result_dir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    directory = Path(result_dir)
    summary = json.loads((directory / 'summary.json').read_text())
    telemetry = directory / 'telemetry.csv'
    if not telemetry.exists():
        raise ValueError('No telemetry.csv: the run may have failed before measurement')
    with telemetry.open(newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError('No telemetry samples to plot')
    commands_path = directory / 'commands.json'
    commands = json.loads(commands_path.read_text()) if commands_path.exists() else summary.get('command_events', [])
    parameters = summary.get('parameters', {})
    t = [float(r['wall_elapsed_s']) for r in rows]
    fig, axes = plt.subplots(3, 2, figsize=(14, 12), constrained_layout=True)
    def series(key):
        return [float(r.get(key, 'nan')) for r in rows]
    def unavailable(ax, label):
        ax.text(.5, .5, label, ha='center', va='center', transform=ax.transAxes)
    milestones = [
        (parameters.get('inject_at'), 'Configured injection', 'gray', ':'),
        (summary.get('first_undelivered_heartbeat_s'), 'First undelivered heartbeat', 'tab:orange', ':'),
        (summary.get('failsafe_detection_s'), 'Timeout / hover request', 'tab:red', '--'),
        (summary.get('recovery_observed_s'), 'Stable recovery confirmed', 'tab:green', '-.')]
    # Baseline arms may detect timeout without issuing a hover command.
    if parameters.get('recovery', summary.get('recovery_mode')) == 'none':
        milestones[2] = (milestones[2][0], 'Timeout detected (no recovery)', 'tab:red', '--')
    def mark_events(ax):
        for at, label, color, style in milestones:
            if at is not None and t[0] <= at <= t[-1]:
                ax.axvline(at, color=color, linestyle=style, alpha=.8, label=label)
        ax.set_xlabel('Elapsed wall time (s)')
        ax.grid(alpha=.25)

    try:
        ax = axes[0, 0]
        if 'speed_mps' in rows[0]:
            ax.plot(t, series('speed_mps'), label='Measured speed')
        else:
            unavailable(ax, 'Speed not recorded in this version')
        if parameters.get('safe_speed') is not None:
            ax.axhline(parameters['safe_speed'], color='black', linestyle=':', label='Low-speed threshold')
        ax.set(title='Vehicle speed and recovery', ylabel='Speed (m/s)')
        mark_events(ax)
        ax.set_ylim(bottom=0)

        ax = axes[0, 1]
        ax.plot(t, series('heartbeat_age_s'), label='Heartbeat age')
        if parameters.get('timeout') is not None:
            ax.axhline(parameters['timeout'], color='black', linestyle=':', label='Timeout threshold')
        lost = [i for i, r in enumerate(rows) if r.get('heartbeat_delivered') in ('0', 'False')]
        ax.scatter([t[i] for i in lost], [0]*len(lost), marker='|', color='tab:orange', label='Undelivered heartbeat', s=20)
        ax.set(title='Communication watchdog', ylabel='Heartbeat age (s)')
        mark_events(ax)
        ax.set_ylim(bottom=0)

        ax = axes[1, 0]
        ax.plot(series('x'), series('y'), label='Observed XY path', color='tab:blue')
        detection, recovery = summary.get('failsafe_detection_s'), summary.get('recovery_observed_s')
        if detection is not None:
            ids = [i for i, at in enumerate(t) if at >= detection and (recovery is None or at <= recovery)]
            ax.plot([series('x')[i] for i in ids], [series('y')[i] for i in ids], color='tab:red', linewidth=2, label='Recovery observation interval')
        for at, label, color, _ in milestones[1:]:
            if at is not None and t[0] <= at <= t[-1]:
                i = min(range(len(t)), key=lambda j: abs(t[j]-at))
                ax.scatter(float(rows[i]['x']), float(rows[i]['y']), color=color, label=label, s=50)
        ax.set(title='XY trajectory (AirSim local frame)', xlabel='X (m)', ylabel='Y (m)')
        ax.set_aspect('equal', adjustable='datalim')
        ax.grid(alpha=.25)

        ax = axes[1, 1]
        labels = ['accepted', 'dropped', 'expired', 'suppressed_after_timeout', 'duplicate_or_out_of_order', 'oba_rejected']
        if commands:
            labels += sorted(set(c['decision'] for c in commands)-set(labels))
            for index, label in enumerate(labels):
                selected = [c for c in commands if c['decision'] == label]
                if selected:
                    ax.scatter([c['received_at_s'] for c in selected], [index]*len(selected), label=label, s=35)
            ax.set_yticks(range(len(labels)), [label.replace('_', ' ') for label in labels], fontsize=8)
        else:
            unavailable(ax, 'No LLM/replay command events recorded')
        ax.set_title('Command receiver decisions')
        mark_events(ax)

        ax = axes[2, 0]
        if 'height_above_configured_ground_m' in rows[0]:
            ax.plot(t, series('height_above_configured_ground_m'), label='Height above configured ground')
            if parameters.get('cruise_height') is not None:
                ax.axhline(parameters['cruise_height'], color='black', linestyle=':', label='Mission cruise height')
            ax.set_ylabel('Height above configured ground (m)')
        else:
            ax.plot(t, [-z for z in series('z')], label='Height relative to AirSim origin')
            ax.set_ylabel('Origin-relative height (m)')
        ax.set_title('Vertical motion (configured ground is not sensed terrain)')
        mark_events(ax)

        ax = axes[2, 1]
        latency_commands = [c for c in commands if c.get('inference_latency_s') is not None]
        if latency_commands:
            ax.scatter([c['received_at_s'] for c in latency_commands], [c['inference_latency_s'] for c in latency_commands], label='Completed command inference latency')
        else:
            unavailable(ax, 'No successful command inference timings')
        failures = [e for e in summary.get('events', []) if e['event'] == 'llm_request_failed']
        if failures:
            ax.scatter([e['elapsed_s'] for e in failures], [e.get('inference_latency_s', 0) for e in failures], marker='x', color='tab:red', label='Failed inference requests')
        ax.set(title='Inference latency (separate from heartbeat timeout)', ylabel='Latency (s)')
        mark_events(ax)
        ax.set_ylim(bottom=0)
        for ax in axes.flat:
            handles, labels = ax.get_legend_handles_labels()
            if handles:
                ax.legend(fontsize=7, loc='best')
        mode = parameters.get('recovery', summary.get('recovery_mode', 'unknown'))
        fig.suptitle(f'Experiment D: {mode}; status={summary.get("status", "unknown")}; '
                     f'collision observed={summary.get("collision_seen", "not recorded")}\n'
                     'Application-channel faults; AirSim RPC remains available. Raw sampled data; no smoothing.')
        fig.savefig(directory / 'resilience_metrics.png', dpi=170)
        fig.savefig(directory / 'resilience_metrics.pdf')
    finally:
        plt.close(fig)
    metrics = recovery_distances(rows, summary)
    metrics.update(detection_latency_from_loss_streak_s=summary.get('detection_latency_from_loss_streak_s'),
                   recovery_time_from_detection_s=summary.get('recovery_time_from_detection_s'),
                   note='Distances are 3D sampled path/displacement from timeout through stable-recovery confirmation; null if unobserved or insufficient samples.')
    (directory / 'plot_metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
    return directory / 'resilience_metrics.png'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result-dir', required=True)
    print(generate_plots(parser.parse_args().result_dir))
