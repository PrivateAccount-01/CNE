"""Offline native desktop app backed by real local model and actual CNE."""
import argparse,io,json,queue,threading,traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from PIL import Image,ImageTk
from field_analyst import LABELS,WARNING
from field_analyst.records import Records
from field_analyst.engine import FieldEngine
from field_analyst.onnx_asset import load_asset

class App:
    def __init__(self,root,model,manifest,db):
        self.root=root;root.title('CNE Field Analyst — local CPU');root.geometry('1050x780');root.minsize(760,600)
        self.store=Records(db);self.engine=FieldEngine(load_asset(model,manifest));self.observation=None;self.photo=None;self.plant_ids=[];self.observation_ids=[]
        self.closed=False;self.completions=queue.Queue()
        frame=ttk.Frame(root,padding=18);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='CNE Field Analyst',font=('Segoe UI',24,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Offline • CPU inference • experimental tomato image classification').pack(anchor='w')
        ttk.Label(frame,text=WARNING,wraplength=980,foreground='#6b4916').pack(fill='x',pady=10)
        limitation='Verified PlantVillage subset only; field and unsupported-input reliability are not established.'
        evidence=Path('field_analyst/reports/local-real-proof.json')
        if evidence.exists():
            report=json.loads(evidence.read_text())
            if report.get('model_sha256')==self.engine.asset.manifest['sha256']:
                field=report.get('field_evaluation_provisional');unknown=report.get('unknown_evaluation')
                if field and unknown:
                    limitation=f"Limited field performance: {field['accuracy']:.1%} provisional accuracy. Unknown false acceptance: {unknown['operating_point']['unknown_false_accept']:.1%}. Experimental use only."
        ttk.Label(frame,text=limitation,wraplength=980,foreground='#9c261d').pack(fill='x',pady=(0,8))
        controls=ttk.Frame(frame);controls.pack(fill='x');self.plants=ttk.Combobox(controls,state='readonly',width=32);self.plants.pack(side='left');self.plants.bind('<<ComboboxSelected>>',lambda e:self.refresh_history())
        self.name=ttk.Entry(controls);self.name.pack(side='left',padx=8);ttk.Button(controls,text='Create plant',command=self.create).pack(side='left')
        panes=ttk.Panedwindow(frame,orient='horizontal');panes.pack(fill='both',expand=True,pady=12);left=ttk.Frame(panes);right=ttk.Frame(panes);panes.add(left,weight=1);panes.add(right,weight=2)
        ttk.Label(left,text='Observation history').pack(anchor='w');self.history=tk.Listbox(left,width=35,height=16,exportselection=False);self.history.pack(fill='both',expand=True);self.history.bind('<<ListboxSelect>>',lambda e:self.select())
        self.preview=ttk.Label(right,text='Import a leaf photo to begin',anchor='center');self.preview.pack(fill='both',expand=True)
        ttk.Label(right,text='Note').pack(anchor='w');self.note=tk.Text(right,height=3,wrap='word');self.note.pack(fill='x')
        buttons=ttk.Frame(right);buttons.pack(fill='x',pady=8);ttk.Button(buttons,text='Import photo',command=self.import_photo).pack(side='left');self.analyze_button=ttk.Button(buttons,text='Analyze locally',command=self.analyze);self.analyze_button.pack(side='left',padx=8);ttk.Button(buttons,text='Save note',command=self.save_note).pack(side='left')
        self.result=tk.Text(frame,height=10,wrap='word',font=('Consolas',10));self.result.pack(fill='x');self.status=tk.StringVar(value='Real model loaded: '+Path(model).name+' • CPU only');ttk.Label(frame,textvariable=self.status).pack(anchor='w',pady=6)
        self.refresh_plants();root.protocol('WM_DELETE_WINDOW',self.close)
        self.poll_callback=root.after(50,self.poll_completions)
    def refresh_plants(self):
        rows=list(self.store.db.execute('SELECT id,name FROM plants ORDER BY name,id'));self.plant_ids=[r[0] for r in rows];self.plants['values']=[r[1] for r in rows]
        if rows:self.plants.current(0);self.refresh_history()
    def create(self):
        try:self.store.create_plant(self.name.get());self.name.delete(0,'end');self.refresh_plants()
        except Exception as e:messagebox.showerror('Plant',str(e))
    def refresh_history(self):
        self.history.delete(0,'end');self.observation_ids=[]
        i=self.plants.current()
        if i<0:return
        for r in reversed(self.store.history(self.plant_ids[i])):
            self.history.insert('end',r['captured_at'][:19]+'  '+r['note'][:24]);self.observation_ids.append(r['id'])
    def import_photo(self):
        if self.plants.current()<0:messagebox.showinfo('Plant','Create a plant first.');return
        path=filedialog.askopenfilename(title='Import real leaf photo',filetypes=[('Images','*.jpg *.jpeg *.png *.bmp *.webp'),('All files','*.*')])
        if not path:return
        try:
            self.observation=self.store.add(self.plant_ids[self.plants.current()],Path(path).read_bytes(),self.note.get('1.0','end-1c'));self.refresh_history();self.show(self.observation)
        except Exception as e:messagebox.showerror('Photo',str(e))
    def select(self):
        sel=self.history.curselection()
        if sel:self.observation=self.observation_ids[sel[0]];self.show(self.observation)
    def show(self,oid):
        row=self.store.db.execute('SELECT image,note,result FROM observations WHERE id=?',(oid,)).fetchone()
        from field_analyst.dataset import image_rgb
        im=image_rgb(row[0]);im.thumbnail((600,310));self.photo=ImageTk.PhotoImage(im);self.preview.configure(image=self.photo,text='');self.note.delete('1.0','end');self.note.insert('1.0',row[1]);self.result.delete('1.0','end')
        if row[2]:self.render(json.loads(row[2]))
    def save_note(self):
        if self.observation:self.store.update_note(self.observation,self.note.get('1.0','end-1c'));self.refresh_history()
    def render(self,r):
        from field_analyst.uncertainty import assess_scores
        # Historical saved records may predate the current abstention policy.
        uncertainty=assess_scores([x['softmax_score'] for x in r['ranked']],r.get('threshold'))
        self.result.delete('1.0','end');lines=['Ranked model outputs (softmax scores, not diagnosis probabilities):']
        lines.extend(f"{x['label']}: {x['softmax_score']:.4f}" for x in r['ranked'])
        lines.extend(['',uncertainty['uncertainty_status'],'Trace: '+json.dumps(r['trace'],sort_keys=True)])
        self.result.insert('1.0','\n'.join(lines))
    def analyze(self):
        if not self.observation:messagebox.showinfo('Photo','Import or select a photo first.');return
        self.save_note();oid=self.observation;row=self.store.db.execute('SELECT image,note,image_sha256 FROM observations WHERE id=?',(oid,)).fetchone()
        from field_analyst.dataset import digest
        if digest(row[0])!=row[2]:messagebox.showerror('Integrity','Stored photo hash mismatch');return
        self.analyze_button.configure(state='disabled');self.status.set('Running actual local model through CNE…')
        def work():
            try:self.completions.put((oid,self.engine.analyze(row[0],row[1]),None))
            except Exception as e:self.completions.put((oid,None,str(e)))
        threading.Thread(target=work,daemon=True).start()
    def poll_completions(self):
        if self.closed:return
        while True:
            try:completion=self.completions.get_nowait()
            except queue.Empty:break
            self.finished(*completion)
        self.poll_callback=self.root.after(50,self.poll_completions)
    def finished(self,oid,result,error):
        if self.closed:return
        self.analyze_button.configure(state='normal')
        if error:self.status.set('Analysis failed');messagebox.showerror('Analysis',error);return
        with self.store.db:self.store.db.execute('UPDATE observations SET result=? WHERE id=?',(json.dumps(result),oid))
        if self.observation==oid:self.render(result)
        self.status.set(f"Local CPU analysis saved • {result['trace']['elapsed_ns']/1e6:.1f} ms • model calls {result['trace']['inference_calls']}")
    def close(self):
        self.closed=True;self.root.after_cancel(self.poll_callback);self.store.close();self.root.destroy()

def main():
    p=argparse.ArgumentParser();p.add_argument('--model');p.add_argument('--model-manifest');p.add_argument('--db',default='field_analyst/data/local-records.db');a=p.parse_args()
    if not a.model:
        deployed=Path('field_analyst/deploy')
        if (deployed/'model.onnx').exists():
            a.model=str(deployed/'model.onnx');a.model_manifest=str(deployed/'model.json')
    if not a.model:
        out=Path('field_analyst/runs/onnx');selection=out/('selection.json' if (out/'selection.json').exists() else 'comparison.json');choice=json.loads(selection.read_text())['chosen'];a.model=str(out/(choice+'.onnx'));a.model_manifest=str(out/(choice+'.json'))
    root=tk.Tk();App(root,a.model,a.model_manifest,a.db);root.mainloop()
if __name__=='__main__':main()
