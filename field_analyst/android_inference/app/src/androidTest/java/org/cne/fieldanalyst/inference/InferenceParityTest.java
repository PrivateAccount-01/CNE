package org.cne.fieldanalyst.inference;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.core.app.ActivityScenario;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import android.content.Context;
import android.util.Base64;
import com.chaquo.python.Python;
import java.io.*;
import java.nio.*;
import org.json.*;

/** Real runtime/core instrumentation. Missing staged references fails, never skips. */
@RunWith(AndroidJUnit4.class)
public class InferenceParityTest {
    byte[] read(String name) throws Exception {
        try(InputStream in=InstrumentationRegistry.getInstrumentation().getContext().getAssets().open(name);ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))!=-1)out.write(buffer,0,n);return out.toByteArray();
        }
    }
    @Test public void testActualCpuCoreAndReferenceParity() throws Exception {
        Context app=InstrumentationRegistry.getInstrumentation().getTargetContext();JSONArray refs=new JSONArray(new String(read("references.json"),"UTF-8"));
        assertEquals(3,refs.length());
        for(int index=0;index<refs.length();index++){
            JSONObject reference=refs.getJSONObject(index);byte[] image=read(reference.getString("image"));
            assertEquals(reference.getString("image_sha256"),NativeModel.sha(image));
            JSONObject baseline=new JSONObject(InferenceHost.analyze(app,image,"reference",true));
            JSONObject cne=new JSONObject(InferenceHost.analyze(app,image,"note only",false));
            android.os.Bundle measured=new android.os.Bundle();
            measured.putString("reference_image_sha256",reference.getString("image_sha256"));
            measured.putString("baseline_actual_result",baseline.toString());
            measured.putString("cne_actual_result",cne.toString());
            InstrumentationRegistry.getInstrumentation().sendStatus(0,measured);
            assertFalse(cne.getJSONObject("trace").getBoolean("reused_state"));
            assertEquals(1,cne.getJSONObject("trace").getInt("inference_calls"));
            assertTrue(cne.getJSONObject("trace").getBoolean("contract_satisfied"));
            assertTrue(cne.isNull("accepted"));assertTrue(cne.getBoolean("abstained"));
            assertEquals(reference.getString("image_sha256"),cne.getJSONObject("trace").getString("image_sha256"));
            JSONArray expected=reference.getJSONArray("logits"),actual=cne.getJSONArray("logits");
            assertEquals(4,actual.length());
            for(int j=0;j<4;j++){
                double value=actual.getDouble(j),ref=expected.getDouble(j);
                assertTrue(Double.isFinite(value));assertEquals(ref,value,1e-5+1e-5*Math.abs(ref));
                assertEquals(baseline.getJSONArray("logits").getDouble(j),value,0.);
                assertEquals(reference.getJSONArray("ranked_labels").getString(j),cne.getJSONArray("ranked").getJSONObject(j).getString("label"));
            }
            byte[] actualBytes=Base64.decode(Python.getInstance().getModule("android_bridge").callAttr("reference_tensor",Base64.encodeToString(image,Base64.NO_WRAP)).toString(),Base64.DEFAULT);
            byte[] expectedBytes=read(reference.getString("tensor"));assertEquals(3*224*224*4,actualBytes.length);assertEquals(expectedBytes.length,actualBytes.length);
            assertEquals(reference.getString("tensor_sha256"),NativeModel.sha(expectedBytes));
            android.os.Bundle tensors=new android.os.Bundle();
            tensors.putString("android_tensor_sha256",NativeModel.sha(actualBytes));
            tensors.putString("reference_tensor_sha256",NativeModel.sha(expectedBytes));
            InstrumentationRegistry.getInstrumentation().sendStatus(0,tensors);
            FloatBuffer a=ByteBuffer.wrap(actualBytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
            FloatBuffer e=ByteBuffer.wrap(expectedBytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
            while(a.hasRemaining()){float value=a.get(),ref=e.get();assertTrue(Float.isFinite(value));assertEquals(ref,value,1e-6+1e-5*Math.abs(ref));}
        }
        try{InferenceHost.analyze(app,new byte[]{0,1,2},"malformed",false);fail("Malformed photo accepted");}catch(com.chaquo.python.PyException expected){}
    }

    @Test public void testObservationSurvivesRecreationAndStoresRealInference() throws Exception {
        JSONArray refs=new JSONArray(new String(read("references.json"),"UTF-8"));
        JSONObject ref=refs.getJSONObject(0);byte[] photo=read(ref.getString("image"));
        java.util.concurrent.atomic.AtomicLong oid=new java.util.concurrent.atomic.AtomicLong(-1);
        try(ActivityScenario<MainActivity> scenario=ActivityScenario.launch(MainActivity.class)){
            scenario.onActivity(activity->{
                activity.name.setText("instrumented tomato");
                for(int i=0;i<activity.body.getChildCount();i++){
                    android.view.View view=activity.body.getChildAt(i);
                    if(view instanceof android.widget.Button && ((android.widget.Button)view).getText().toString().equals("Create plant")){view.performClick();break;}
                }
                assertTrue(activity.selected>0);
                try{
                    try(FileOutputStream output=new FileOutputStream(new File(activity.getFilesDir(),"pending_capture.jpg"))){output.write(photo);}
                    activity.pendingPlant=activity.selected;activity.pendingNote="integration camera-result fixture";
                    // Real Activity camera-result handler, supplied an existing validation photo.
                    // This is a flow fixture, never a newly captured field photograph.
                    activity.onActivityResult(2,android.app.Activity.RESULT_OK,null);
                    try(android.database.Cursor cursor=activity.db.rawQuery("SELECT id,sha FROM observations WHERE plant=? ORDER BY id DESC LIMIT 1",new String[]{""+activity.selected})){
                        assertTrue(cursor.moveToFirst());oid.set(cursor.getLong(0));assertEquals(NativeModel.sha(photo),cursor.getString(1));
                    }
                    activity.analyzeObservation(oid.get(),photo,"integration camera-result fixture");
                }catch(Exception error){throw new RuntimeException(error);}
            });
            scenario.recreate();
            java.util.concurrent.atomic.AtomicReference<String> stored=new java.util.concurrent.atomic.AtomicReference<>();
            long deadline=android.os.SystemClock.elapsedRealtime()+90000;
            while(stored.get()==null && android.os.SystemClock.elapsedRealtime()<deadline){
                scenario.onActivity(activity->{
                    try(android.database.Cursor cursor=activity.db.rawQuery("SELECT result,note,image FROM observations WHERE id=?",new String[]{""+oid.get()})){
                        assertTrue(cursor.moveToFirst());assertEquals("integration camera-result fixture",cursor.getString(1));
                        assertTrue(new File(activity.getFilesDir(),cursor.getString(2)).isFile());
                        if(!cursor.isNull(0))stored.set(cursor.getString(0));
                    }
                });
                if(stored.get()==null)Thread.sleep(100);
            }
            assertNotNull("Real inference result was not saved after recreation",stored.get());
            JSONObject result=new JSONObject(stored.get());assertTrue(result.isNull("accepted"));
            assertTrue(result.getJSONObject("trace").getBoolean("contract_satisfied"));
            assertEquals(1,result.getJSONObject("trace").getInt("inference_calls"));
            assertFalse(result.getJSONObject("trace").getBoolean("reused_state"));
        }
    }
}
