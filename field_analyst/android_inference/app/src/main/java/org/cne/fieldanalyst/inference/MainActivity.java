package org.cne.fieldanalyst.inference;
import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.graphics.*;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.view.*;
import android.widget.*;
import java.io.*;
import java.security.MessageDigest;
import java.text.DateFormat;
import java.util.*;

public class MainActivity extends Activity {
    SQLiteDatabase db; LinearLayout body; EditText name,note; Spinner plants; long selected=-1; long pendingPlant=-1; String pendingNote="";
    final String warning="Experimental image classification is not a diagnosis. Healthy is not proof of plant health. Photo comparisons depend on lighting, view, leaf and capture conditions.";
    final String blocked="Local CPU model through the actual CNE core. Unknown-input reliability is unverified; all rankings are inspection-only.";
    boolean destroyed=false; final java.util.Set<Long> running=new java.util.HashSet<>();
    final android.os.Handler refreshHandler=new android.os.Handler(android.os.Looper.getMainLooper());
    long seenRevision=InferenceHost.REVISION.get();
    final Runnable refreshCompleted=new Runnable(){public void run(){
        if(destroyed)return;
        long current=InferenceHost.REVISION.get();
        if(current!=seenRevision){seenRevision=current;show(note==null?"":note.getText().toString());}
        refreshHandler.postDelayed(this,500);
    }};
    public void onCreate(Bundle state){super.onCreate(state);
        db=openOrCreateDatabase("field.db",MODE_PRIVATE,null);
        db.execSQL("PRAGMA foreign_keys=ON");
        db.execSQL("CREATE TABLE IF NOT EXISTS plants(id INTEGER PRIMARY KEY,name TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,plant INTEGER NOT NULL REFERENCES plants(id),time INTEGER NOT NULL,image TEXT NOT NULL,sha TEXT NOT NULL,note TEXT NOT NULL,result TEXT)");
        if(state!=null){selected=state.getLong("plant",-1); pendingPlant=state.getLong("pendingPlant",-1); pendingNote=state.getString("pendingNote","");}
        show(state==null?"":state.getString("draft",""));
        refreshHandler.postDelayed(refreshCompleted,500);
    }
    TextView text(String value,int size){TextView v=new TextView(this);v.setText(value);v.setTextSize(size);v.setTextColor(Color.rgb(25,48,36));v.setPadding(0,12,0,12);body.addView(v);return v;}
    void button(String label,Runnable action){Button b=new Button(this);b.setText(label);b.setAllCaps(false);b.setOnClickListener(v->action.run());body.addView(b);}
    void show(String draft){
        ScrollView scroll=new ScrollView(this); body=new LinearLayout(this);body.setOrientation(LinearLayout.VERTICAL);body.setPadding(24,36,24,36);body.setBackgroundColor(Color.rgb(246,249,242));scroll.addView(body);setContentView(scroll);
        if(android.os.Build.VERSION.SDK_INT>=35)body.setOnApplyWindowInsetsListener((v,i)->{android.graphics.Insets bars=i.getInsets(WindowInsets.Type.systemBars());v.setPadding(24,24+bars.top,24,24+bars.bottom);return i;});
        text("CNE Field Analyst",28);text("Local observations • experimental",18);text(warning,15);text(blocked,16);
        text("Candidate labels: healthy, Early blight, Late blight, Bacterial spot (tomato only). Scores are experimental and never establish plant health.",14);
        name=new EditText(this);name.setHint("New plant name");name.setContentDescription("New plant name");body.addView(name);
        button("Create plant",()->{String n=name.getText().toString().trim();if(n.isEmpty()){toast("Enter a plant name");return;}ContentValues v=new ContentValues();v.put("name",n);selected=db.insertOrThrow("plants",null,v);show("");});
        List<Long> ids=new ArrayList<>();List<String> names=new ArrayList<>();int index=0;
        try(Cursor c=db.rawQuery("SELECT id,name FROM plants ORDER BY id",null)){while(c.moveToNext()){if(c.getLong(0)==selected)index=ids.size();ids.add(c.getLong(0));names.add(c.getString(1));}}
        if(ids.isEmpty()){text("Create a plant to add observations.",16);button("Source and license notices",this::notices);return;}
        selected=ids.get(index);plants=new Spinner(this);plants.setContentDescription("Selected plant");plants.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,names));plants.setSelection(index);body.addView(plants);
        plants.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){public void onNothingSelected(android.widget.AdapterView<?> p){}public void onItemSelected(android.widget.AdapterView<?> p,View v,int i,long id){if(selected!=ids.get(i)){selected=ids.get(i);show("");}}});
        note=new EditText(this);note.setHint("Observation note");note.setContentDescription("Observation note");note.setText(draft);body.addView(note);
        button("Import photo",()->capture(false));button("Photograph leaf",()->capture(true));
        button("Diagnostic trace",()->new AlertDialog.Builder(this).setTitle("Execution policy").setMessage("CPU only. Native result reuse disabled. Per-observation traces appear after real inference. No network permission.").setPositiveButton("Close",null).show());
        text("Plant history",22);
        try(Cursor c=db.rawQuery("SELECT id,time,image,sha,note,result FROM observations WHERE plant=? ORDER BY time DESC,id DESC LIMIT 20",new String[]{""+selected})){
            while(c.moveToNext()){
                long oid=c.getLong(0);byte[] bytes;
                try{bytes=readPhoto(c.getString(2));}catch(Exception e){text("Photo unavailable: "+e.getMessage(),16);continue;}
                String oldNote=c.getString(4);
                text(DateFormat.getDateTimeInstance().format(new Date(c.getLong(1))),16);
                if(!sha(bytes).equals(c.getString(3))){text("Photo integrity check failed",16);continue;}
                BitmapFactory.Options opts=new BitmapFactory.Options();opts.inJustDecodeBounds=true;BitmapFactory.decodeByteArray(bytes,0,bytes.length,opts);
                opts.inSampleSize=Math.max(1,Math.max(opts.outWidth,opts.outHeight)/900);opts.inJustDecodeBounds=false;
                Bitmap bitmap=BitmapFactory.decodeByteArray(bytes,0,bytes.length,opts);ImageView preview=new ImageView(this);preview.setImageBitmap(bitmap);preview.setAdjustViewBounds(true);preview.setMaxHeight(700);preview.setContentDescription("Saved leaf photo; visual comparison depends on capture conditions");body.addView(preview);
                text(oldNote,16);text("SHA-256 "+c.getString(3),12);
                if(!c.isNull(5))text(c.getString(5),12);
                button(running.contains(oid)?"Analysis running?":"Analyze locally",()->analyzeObservation(oid,bytes,oldNote));
                button("Edit observation note",()->{EditText edit=new EditText(this);edit.setText(oldNote);new AlertDialog.Builder(this).setTitle("Edit note").setView(edit).setPositiveButton("Save",(d,w)->{ContentValues v=new ContentValues();v.put("note",edit.getText().toString());db.update("observations",v,"id=?",new String[]{""+oid});show("");}).setNegativeButton("Cancel",null).show();});
            }
        }
        button("Source and license notices",this::notices);
    }
    void capture(boolean camera){pendingPlant=selected;pendingNote=note.getText().toString();
        try{if(camera){new File(getFilesDir(),"pending_capture.jpg").delete();Intent i=new Intent(MediaStore.ACTION_IMAGE_CAPTURE);Uri u=Uri.parse("content://org.cne.fieldanalyst.inference.capture/photo");i.putExtra(MediaStore.EXTRA_OUTPUT,u);i.setClipData(ClipData.newRawUri("Leaf photo",u));i.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);startActivityForResult(i,2);}
        else{Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT);i.setType("image/*");i.addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(i,1);}}
        catch(Exception e){toast("Camera or picker unavailable or access denied");}
    }
    protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(result!=RESULT_OK){toast("No photo saved");return;}
        try(InputStream in=request==2?new FileInputStream(new File(getFilesDir(),"pending_capture.jpg")):getContentResolver().openInputStream(data.getData())){
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))!=-1){if(out.size()+n>32*1024*1024)throw new IOException("Image exceeds 32 MiB");out.write(buffer,0,n);}byte[] bytes=out.toByteArray();
            BitmapFactory.Options opts=new BitmapFactory.Options();opts.inJustDecodeBounds=true;BitmapFactory.decodeByteArray(bytes,0,bytes.length,opts);
            if(opts.outWidth<=0 || opts.outHeight<=0 || (long)opts.outWidth*opts.outHeight>25000000)throw new IOException("Unsupported or oversized photo");
            ContentValues v=new ContentValues();v.put("plant",pendingPlant);v.put("time",System.currentTimeMillis());String photo=savePhoto(bytes);v.put("image",photo);v.put("sha",sha(bytes));v.put("note",pendingNote);
            try{db.insertOrThrow("observations",null,v);}catch(Exception e){new File(getFilesDir(),photo).delete();throw e;}
            selected=pendingPlant;show("");
        }catch(Exception e){toast("Photo not saved: "+e.getMessage());}
    }
    byte[] readPhoto(String relative) throws IOException {
        File image=new File(getFilesDir(),relative);File directory=new File(getFilesDir(),"images");
        if(!image.getCanonicalPath().startsWith(directory.getCanonicalPath()+File.separator) || image.length()>32*1024*1024)throw new IOException("Invalid photo storage");
        try(InputStream in=new FileInputStream(image);ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))!=-1){if(out.size()+n>32*1024*1024)throw new IOException("Photo too large");out.write(buffer,0,n);}return out.toByteArray();
        }
    }
    String savePhoto(byte[] bytes) throws IOException {
        File directory=new File(getFilesDir(),"images");if(!directory.exists() && !directory.mkdirs())throw new IOException("Storage unavailable");
        long used=0;File[] photos=directory.listFiles();if(photos==null)throw new IOException("Storage unavailable");
        for(File f:photos)used+=f.length();
        if(used+bytes.length>256L*1024*1024)throw new IOException("Local photo storage limit reached (256 MiB)");
        String relative="images/"+UUID.randomUUID()+".bin";File photo=new File(getFilesDir(),relative);
        try(FileOutputStream out=new FileOutputStream(photo)){out.write(bytes);out.getFD().sync();}
        catch(IOException e){photo.delete();throw e;}
        return relative;
    }
    void analyzeObservation(long oid,byte[] bytes,String oldNote){
        if(!InferenceHost.BUSY.compareAndSet(false,true)){toast("Analysis already running; wait for it to finish");return;}
        running.add(oid);
        final android.content.Context app=getApplicationContext();toast("Running local CPU inference?");
        InferenceHost.WORKER.execute(()->{
            try{
                String result=InferenceHost.analyze(app,bytes,oldNote,false);
                // Worker owns its connection: closing/rotating the Activity is safe.
                try(SQLiteDatabase workerDb=SQLiteDatabase.openDatabase(app.getDatabasePath("field.db").getPath(),null,SQLiteDatabase.OPEN_READWRITE)){
                    ContentValues value=new ContentValues();value.put("result",result);
                    if(workerDb.update("observations",value,"id=?",new String[]{""+oid})!=1)throw new IOException("Observation disappeared");
                }
                InferenceHost.REVISION.incrementAndGet();
                runOnUiThread(()->{running.remove(oid);if(!destroyed){show(note==null?"":note.getText().toString());toast("Analysis saved; reliability unverified");}});
            }catch(Exception e){runOnUiThread(()->{running.remove(oid);if(!destroyed) new AlertDialog.Builder(this).setTitle("Analysis failed").setMessage(e.toString()).setPositiveButton("Close",null).show();});}
            finally{InferenceHost.BUSY.set(false);}
        });
    }
    String sha(byte[] bytes){try{byte[] h=MessageDigest.getInstance("SHA-256").digest(bytes);StringBuilder s=new StringBuilder();for(byte b:h)s.append(String.format(Locale.ROOT,"%02x",b&255));return s.toString();}catch(Exception e){throw new IllegalStateException(e);}}
    void notices(){try(InputStream in=getAssets().open("NOTICE.txt")){ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[4096];int n;while((n=in.read(b))!=-1)out.write(b,0,n);new AlertDialog.Builder(this).setTitle("Source notices").setMessage(out.toString("UTF-8")).setPositiveButton("Close",null).show();}catch(Exception e){toast("Notices unavailable");}}
    void toast(String s){Toast.makeText(this,s,Toast.LENGTH_LONG).show();}
    protected void onSaveInstanceState(Bundle state){super.onSaveInstanceState(state);state.putLong("plant",selected);state.putLong("pendingPlant",pendingPlant);state.putString("pendingNote",pendingNote);state.putString("draft",note==null?"":note.getText().toString());}
    protected void onDestroy(){destroyed=true;refreshHandler.removeCallbacksAndMessages(null);if(db!=null)db.close();super.onDestroy();}
}
