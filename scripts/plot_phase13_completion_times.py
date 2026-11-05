"""Plot a single seed's no-failure baseline times, retaining censored outcomes."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True)
    p.add_argument('--horizon',type=float,required=True)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--output-prefix',required=True)
    args=p.parse_args()
    if args.horizon<=0:p.error('Horizon must be positive')
    rows=[r for r in json.loads(Path(args.input).read_text()) if r['group']=='baselines' and r['seed']==args.seed]
    conditions=['nominal','moderate','severe','partitioned']
    lookup={(r['condition'],r['architecture']):r for r in rows}
    if len(rows)!=16 or len(lookup)!=16 or any((c,a) not in lookup for c in conditions for a in 'ABCD'):
        p.error('Expected exactly 16 baseline cases for this seed')
    if any(r['status']!='completed' for r in rows):p.error('All baseline tests must have finished')
    colors=['#4878a8','#218c30','#c9b938','#ab3276']
    fig,ax=plt.subplots(figsize=(11.5,6.5),layout='constrained')
    for j,(a,color) in enumerate(zip('ABCD',colors)):
        for i,c in enumerate(conditions):
            r=lookup[c,a];success=r['mission_execution_success']
            if success and r['completion_time_s'] is None:p.error('Successful run is missing its completion time')
            if not success and r['observation_end_s']<args.horizon-.25:
                p.error('Incomplete run did not reach the specified horizon')
            x=i+(j-1.5)*.16
            y=r['completion_time_s'] if success else args.horizon
            ax.scatter(x,y,color=color,marker='o' if success else '^',s=115,zorder=3)
            if success:
                # Offset close C/D labels horizontally to keep both values readable.
                offset=(-8,10) if j==2 else (8,10) if j==3 else (0,10)
                ax.annotate(f'{y:.1f}',(x,y),xytext=offset,textcoords='offset points',
                    ha='right' if j==2 else 'left' if j==3 else 'center',fontsize=11)
    ax.axhline(args.horizon,color='.5',linestyle=':',linewidth=1.5)
    ax.text(3.42,args.horizon+8,f'{args.horizon:g} s limit',ha='right',fontsize=10,color='.35')
    ax.set_xlim(-.55,3.55);ax.set_ylim(0,args.horizon*1.13)
    ax.set_xticks(range(4),[c.title() for c in conditions],fontsize=12)
    ax.set_ylabel('Mission completion / observation time (s)',fontsize=12)
    ax.set_axisbelow(True);ax.grid(axis='y',alpha=.22)
    ax.spines[['top','right']].set_visible(False)
    handles=[Line2D([],[],marker='s',linestyle='',color=color,label=a,markersize=10)
             for a,color in zip('ABCD',colors)]
    ax.legend(handles=handles,ncol=4,loc='upper left',title='Architecture')
    fig.suptitle(f'Phase 13 — {args.horizon:g}-second no-failure baseline\nOne run per condition, seed {args.seed}',fontsize=17)
    ax.set_title('Circles: completed missions; triangles: incomplete at the time limit',fontsize=12,pad=12)
    fig.supxlabel('A: centralized · B: independent LLM · C: decentralized rules · D: decentralized LLM\n'
                  'A/C are deterministic; B/D use the pinned LLM. Incomplete points are censored observations.',fontsize=10)
    out=Path(args.output_prefix);out.parent.mkdir(parents=True,exist_ok=True)
    for ext in ['png','pdf']:fig.savefig(str(out)+'.'+ext,dpi=200)
    plt.close(fig)


if __name__=='__main__':main()
