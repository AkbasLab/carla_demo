import csv,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import argparse
p=argparse.ArgumentParser(description='Plot a Phase 10 multi-seed sweep')
p.add_argument('--input-dir',default='results/phase10/multiseed_1_30')
root=Path(p.parse_args().input_dir)
s=json.loads((root/'comparison.json').read_text())
rows=list(csv.DictReader((root/'trials.csv').open()))
names=['nominal','moderate','severe','partitioned'];colors=['#377eb8','#ff9f1c','#e45756','#8064a2']
fig,axes=plt.subplots(1,3,figsize=(14,4.5))
x=np.arange(4);rates=[100*s[n]['success_rate'] for n in names]
lo=[rates[i]-100*s[n]['success_rate_wilson_95'][0] for i,n in enumerate(names)]
hi=[100*s[n]['success_rate_wilson_95'][1]-rates[i] for i,n in enumerate(names)]
axes[0].bar(x,rates,color=colors,yerr=[np.maximum(lo,0),np.maximum(hi,0)],capsize=5)
axes[0].set_ylim(0,112);axes[0].set_ylabel('Mission success (%)');axes[0].set_title('Success; Wilson 95% intervals')
for i,n in enumerate(names):axes[0].text(i,rates[i]+3,f"{s[n]['successful_missions']}/30",ha='center')
for idx,(field,title,label) in enumerate([('tasks_completed','Completed search tasks','Tasks (of 4)'),('lease_expirations','Task/version lease expirations','Expirations')],1):
 vals=[[float(r[field]) for r in rows if r['condition']==n] for n in names]
 axes[idx].boxplot(vals,positions=x,widths=.5,showfliers=False)
 for i,v in enumerate(vals):
  axes[idx].scatter(np.linspace(i-.13,i+.13,len(v)),v,color=colors[i],s=15,alpha=.6)
 axes[idx].set_title(title);axes[idx].set_ylabel(label)
for ax in axes:
 ax.set_xticks(x,names,rotation=20);ax.grid(axis='y',alpha=.25);ax.set_axisbelow(True)
fig.suptitle('Phase 10: matched seeds 1–30; fixed mock mission, no injected drone failure')
fig.text(.5,.01,'Maximum horizon: 120 simulated seconds. Points represent individual trials; network settings vary by condition.',ha='center',fontsize=9)
fig.tight_layout(rect=[0,.04,1,.94])
for ext in ['png','pdf']:fig.savefig(root/f'comparison.{ext}',dpi=180)
