package org.cne.fieldanalyst.inference;

import android.content.Context;
import ai.onnxruntime.*;
import java.io.*;
import java.nio.FloatBuffer;
import java.security.MessageDigest;
import java.util.*;
import org.json.JSONObject;

/** CPU-only verified immutable model snapshot; no memoization or CNE policy here. */
public final class NativeModel {
    private final Context context;
    private final JSONObject bundle;
    private final OrtEnvironment environment;
    private final OrtSession session;
    private final OrtSession.SessionOptions options;
    private final String input;
    public NativeModel(Context context,String bundleJson) throws Exception {
        this.context=context.getApplicationContext();bundle=new JSONObject(bundleJson);verify();
        environment=OrtEnvironment.getEnvironment();
        if (!"1.20.0".equals(environment.getVersion()))throw new IOException("ORT version mismatch");
        options=new OrtSession.SessionOptions();options.setIntraOpNumThreads(1);options.setInterOpNumThreads(1);
        options.setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL);
        options.addConfigEntry("session.use_deterministic_compute","1");options.addCPU(true);
        byte[] bytes=read("model.onnx");
        if(!sha(bytes).equals(bundle.getJSONObject("assets_sha256").getString("model.onnx")))throw new IOException("Model changed while loading");
        session=environment.createSession(bytes,options);input=session.getInputNames().iterator().next();
        NodeInfo info=session.getInputInfo().get(input);
        if(!(info.getInfo() instanceof TensorInfo) || !Arrays.equals(((TensorInfo)info.getInfo()).getShape(),new long[]{1,3,224,224}))throw new IOException("Input shape mismatch");
        verify();
    }
    public byte[] read(String name) throws IOException {
        try(InputStream in=context.getAssets().open(name);ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] buffer=new byte[65536];int n;while((n=in.read(buffer))!=-1)out.write(buffer,0,n);return out.toByteArray();
        }
    }
    public synchronized void verify() throws Exception {
        JSONObject hashes=bundle.getJSONObject("assets_sha256");Iterator<String> keys=hashes.keys();
        while(keys.hasNext()){String name=keys.next();if(!sha(read(name)).equals(hashes.getString(name)))throw new IOException("Asset integrity failure: "+name);}
    }
    public synchronized float[] runTensor(float[] inputData) throws Exception {
        if(inputData.length!=3*224*224)throw new IOException("Tensor length mismatch");
        for(float v:inputData)if(!Float.isFinite(v))throw new IOException("Nonfinite tensor");
        verify();
        try(OnnxTensor tensor=OnnxTensor.createTensor(environment,FloatBuffer.wrap(inputData),new long[]{1,3,224,224});
            OrtSession.Result result=session.run(Collections.singletonMap(input,tensor))){
            float[][] logits=(float[][])result.get(0).getValue();
            if(logits.length!=1 || logits[0].length!=4)throw new IOException("Invalid logits shape");
            for(float v:logits[0])if(!Float.isFinite(v))throw new IOException("Nonfinite logits");
            return logits[0].clone();
        }
    }
    public static String sha(byte[] bytes) throws Exception {
        StringBuilder out=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))out.append(String.format(Locale.ROOT,"%02x",b&255));return out.toString();
    }
}
