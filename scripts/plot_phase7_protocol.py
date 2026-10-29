"""Plot Phase 7 messages and agent telemetry from saved JSON; no simulator needed."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path


def protocol_metrics(messages):
    delivered = [m for m in messages if m['status']=='delivered']
    ages = [m['actual_delivery_time']-m['creation_time'] for m in delivered]
    latency = [m['actual_delivery_time']-m['sent_time'] for m in delivered]
    def stats(values):
        if not values:
            return dict(mean=None,p95=None,max=None)
        ordered=sorted(values)
        i=(len(ordered)-1)*.95;lo=math.floor(i);hi=math.ceil(i)
        return dict(mean=sum(values)/len(values),p95=ordered[lo]+(ordered[hi]-ordered[lo])*(i-lo),max=max(values))
    unique = {m['message_id']:m for m in messages}
    return dict(unique_messages_sent=len(unique),recipient_attempts=len(messages),
        recipient_deliveries=len(delivered),delivery_ratio=len(delivered)/len(messages) if messages else None,
        outcomes=dict(Counter(m['status'] for m in messages)),
        unique_message_types=dict(Counter(m['message_type'] for m in unique.values())),
        recipient_delivery_types=dict(Counter(m['message_type'] for m in delivered)),
        serialized_unique_bytes=sum(m['size_bytes'] for m in unique.values()),
        serialized_recipient_bytes=sum(m['size_bytes'] for m in messages),
        decision_influencing_deliveries=sum(bool(m.get('influenced_decision')) for m in delivered),
        send_to_receive_s=stats(latency),creation_to_receive_age_s=stats(ages),
        timing_note='Application inbox polling, including harness processing; not RF/network latency. Legacy tick-clock logs can show zero delay.',
        byte_note='Serialized JSON bytes, not measured wire bandwidth.')


def generate_plots(result_dir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    directory=Path(result_dir)
    messages=json.loads((directory/'messages.json').read_text())
    beliefs=json.loads((directory/'beliefs.json').read_text())
    summary=json.loads((directory/'summary.json').read_text())
    if not messages and not beliefs:
        raise ValueError('No messages or telemetry recorded')
    metrics=protocol_metrics(messages)
    ids=sorted({m['sender_id'] for m in messages}|{m['recipient_id'] for m in messages}|{b['agent_id'] for b in beliefs})
    delivered=[m for m in messages if m['status']=='delivered']
    unique={m['message_id']:m for m in messages}
    fig,axes=plt.subplots(3,2,figsize=(14,12),constrained_layout=True)
    def cumulative(ax, times, label):
        times=sorted(times)
        if times: ax.step([0]+times,[0]+list(range(1,len(times)+1)),where='post',label=label)
    try:
        ax=axes[0,0]
        cumulative(ax,[m['sent_time'] for m in unique.values()],'Unique messages sent')
        cumulative(ax,[m['actual_delivery_time'] for m in delivered],'Recipient deliveries')
        ax.set(title='Message traffic (one send may have multiple recipients)',xlabel='Measurement time (s)',ylabel='Cumulative count')
        ax=axes[0,1]
        matrix=[[sum(m['sender_id']==a and m['recipient_id']==b for m in delivered) for b in ids] for a in ids]
        im=ax.imshow(matrix,cmap='Blues',vmin=0)
        fig.colorbar(im,ax=ax,label='Delivered recipient messages')
        ax.set_xticks(range(len(ids)),ids,rotation=30)
        ax.set_yticks(range(len(ids)),ids)
        ax.set(title='Directed communication counts',xlabel='Recipient',ylabel='Sender')
        for i,row in enumerate(matrix):
            for j,value in enumerate(row): ax.text(j,i,str(value),ha='center',va='center',color='black')
        heights_available=bool(beliefs) and all('height_above_start_m' in b for b in beliefs)
        for agent_id in ids:
            samples=sorted([b for b in beliefs if b['agent_id']==agent_id],key=lambda b:b['time_s'])
            if not samples: continue
            times=[b['time_s'] for b in samples]
            axes[1,0].plot(times,[b['height_above_start_m'] if heights_available else -b['own_position'][2] for b in samples],label=agent_id)
            if all('speed_mps' in b for b in samples):
                axes[1,1].plot(times,[b['speed_mps'] for b in samples],label=agent_id)
            axes[2,1].step(times,[len(b.get('team_beliefs',{})) for b in samples],where='post',label=agent_id)
        axes[1,0].set(title='Drone height during message exchange',xlabel='Measurement time (s)',
                      ylabel='Height above each starting reference (m)' if heights_available else 'Origin-relative height −NED Z (m)')
        axes[1,1].set(title='Measured vehicle speed',xlabel='Measurement time (s)',ylabel='Speed (m/s)')
        if not any('speed_mps' in b for b in beliefs):
            axes[1,1].text(.5,.5,'Speed not recorded in this run',ha='center',transform=axes[1,1].transAxes)
        axes[1,1].set_ylim(bottom=0)
        ax=axes[2,0]
        for agent_id in ids:
            rows=[m for m in delivered if m['recipient_id']==agent_id]
            if rows: ax.scatter([m['actual_delivery_time'] for m in rows],
                [1000*(m['actual_delivery_time']-m['sent_time']) for m in rows],s=6,alpha=.5,label=agent_id)
        ax.set(title='Application send → inbox receipt (not RF latency)',xlabel='Measurement time (s)',ylabel='Polling delay (ms)')
        ax.set_ylim(bottom=0)
        axes[2,1].set(title='Local peer-belief coverage after delivery',xlabel='Measurement time (s)',ylabel='Peers represented in local beliefs')
        axes[2,1].axhline(max(0,len(ids)-1),linestyle=':',color='black',label='All peers')
        axes[2,1].set_ylim(-.1,max(1,len(ids)-1)+.5)
        axes[2,1].set_yticks(range(len(ids)))
        for ax in axes.flat:
            if ax is not axes[0,1]:
                ax.grid(alpha=.25)
                handles,labels=ax.get_legend_handles_labels()
                if handles: ax.legend(fontsize=8)
        ratio=metrics['delivery_ratio']
        label=f'{ratio:.1%}' if ratio is not None else 'N/A'
        fig.suptitle(f'Phase 7: {summary.get("mode","protocol")}; {metrics["unique_messages_sent"]} unique messages, '
            f'{metrics["recipient_deliveries"]}/{metrics["recipient_attempts"]} recipient deliveries ({label})\n'
            f'Cleanup warnings: {len(summary.get("cleanup_errors",[]))}; flight/landing safety is separate from protocol delivery')
        fig.savefig(directory/'phase7_metrics.png',dpi=170)
        fig.savefig(directory/'phase7_metrics.pdf')
    finally:
        plt.close(fig)
    (directory/'protocol_metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
    return directory/'phase7_metrics.png'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result-dir',required=True)
    print(generate_plots(parser.parse_args().result_dir))
