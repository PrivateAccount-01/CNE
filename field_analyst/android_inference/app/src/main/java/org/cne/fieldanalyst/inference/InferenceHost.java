package org.cne.fieldanalyst.inference;
import android.content.Context;
import android.util.Base64;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;
import java.nio.charset.StandardCharsets;
import java.io.*;
import java.util.concurrent.*;

/** One process-local worker. Activity recreation does not create duplicate sessions. */
public final class InferenceHost {
    public static final ExecutorService WORKER=Executors.newSingleThreadExecutor();
    public static final java.util.concurrent.atomic.AtomicBoolean BUSY=new java.util.concurrent.atomic.AtomicBoolean();
    public static final java.util.concurrent.atomic.AtomicLong REVISION=new java.util.concurrent.atomic.AtomicLong();
    private static PyObject bridge;
    private static NativeModel nativeModel;
    public static synchronized String analyze(Context context,byte[] image,String note,boolean baseline) throws Exception {
        if(bridge==null){
            Context app=context.getApplicationContext();
            if(!Python.isStarted())Python.start(new AndroidPlatform(app));
            String bundle=read(app,"bundle.json");
            nativeModel=new NativeModel(app,bundle);
            PyObject module=Python.getInstance().getModule("android_bridge");
            module.callAttr("initialize",nativeModel,read(app,"model.json"),read(app,"model-threshold.json"),bundle);
            bridge=module;
        }
        return bridge.callAttr("analyze",Base64.encodeToString(image,Base64.NO_WRAP),note,baseline).toString();
    }
    private static String read(Context context,String name) throws IOException {
        try(InputStream in=context.getAssets().open(name);ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))!=-1)out.write(buffer,0,n);
            return new String(out.toByteArray(),StandardCharsets.UTF_8);
        }
    }
}
