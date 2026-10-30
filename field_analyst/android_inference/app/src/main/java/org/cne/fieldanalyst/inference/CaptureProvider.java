package org.cne.fieldanalyst.inference;
import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import java.io.*;

public class CaptureProvider extends ContentProvider {
    public boolean onCreate() { return true; }
    public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        if (!"/photo".equals(uri.getPath())) throw new FileNotFoundException();
        File file=new File(getContext().getFilesDir(),"pending_capture.jpg");
        return ParcelFileDescriptor.open(file,ParcelFileDescriptor.parseMode(mode));
    }
    public String getType(Uri uri){return "image/jpeg";}
    public Cursor query(Uri u,String[] p,String s,String[] a,String o){return null;}
    public Uri insert(Uri u,ContentValues v){throw new UnsupportedOperationException();}
    public int update(Uri u,ContentValues v,String s,String[] a){throw new UnsupportedOperationException();}
    public int delete(Uri u,String s,String[] a){throw new UnsupportedOperationException();}
}
