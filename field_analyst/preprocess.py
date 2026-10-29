"""Torch-free reference RGB/EXIF/ImageNet preprocessing for lightweight local runtime."""
import numpy as np
from PIL import Image
from field_analyst.dataset import image_rgb
PREPROCESS_VERSION='pv-rgb-exif-bilinear256-center224-imagenet-v1'
PREPROCESS={'version':PREPROCESS_VERSION,'resize_short':256,'crop':224,
            'mean':[.485,.456,.406],'std':[.229,.224,.225],'interpolation':'bilinear','exif_transpose':True}
def tensor(data):
    im=image_rgb(data);w,h=im.size
    if w<=h: nw,nh=256,int(256*h/w)
    else:nw,nh=int(256*w/h),256
    im=im.resize((nw,nh),Image.Resampling.BILINEAR)
    left=int(round((nw-224)/2));top=int(round((nh-224)/2));im=im.crop((left,top,left+224,top+224))
    x=np.asarray(im,dtype=np.float32).transpose(2,0,1)/np.float32(255)
    x=(x-np.asarray([.485,.456,.406],dtype=np.float32)[:,None,None])/np.asarray([.229,.224,.225],dtype=np.float32)[:,None,None]
    return np.ascontiguousarray(x[None],dtype=np.float32)
