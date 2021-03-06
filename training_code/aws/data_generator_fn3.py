
import numpy as np 
import pandas as pd 
import dicom
import os
import scipy.ndimage
from joblib import Parallel, delayed
import SimpleITK as sitk
from scipy import ndimage
import pdb
import warnings

warnings.filterwarnings("ignore")
DATA_DIR = r'/home/ec2-user/data'

def get_target_for(patient,tgt_lookup):
	if patient in tgt_lookup:
		return tgt_lookup[patient]
	else:
		return 'testsg1'
	
def load_itk_image(filename):
	itkimage = sitk.ReadImage(filename)
	numpyImage = sitk.GetArrayFromImage(itkimage)
	numpyOrigin = np.array(list(reversed(itkimage.GetOrigin())))
	numpySpacing = np.array(list(reversed(itkimage.GetSpacing())))
	return numpyImage, numpyOrigin, numpySpacing
	
def worldToVoxelCoord(worldCoord, origin, spacing):
	stretchedVoxelCoord = np.absolute(worldCoord - origin)
	voxelCoord = stretchedVoxelCoord / spacing
	return voxelCoord

def resize_voxel(x, desired_shape):
	factors = np.array(x.shape).astype('float32') / np.array(desired_shape).astype('float32')
	assert all(s > 1 for s in x.shape)
	output= ndimage.interpolation.zoom(x,1.0 / factors,order=1)
	assert output.shape == desired_shape, 'resize error'
	return output
	
def get_bounding_voxels_new(patient, df, n,VOXEL_SIZE,img,origin,spacing,rotate=True):
	#given the nodule index and the nodule dataframe
	#return n jittered views of the nodule and n copies of the row index
	#from the row index we can look up the nodule size, malignancy, etc.
	df['ix'] = range(df.shape[0])
	dfsub = df[df['seriesuid']==patient]
	if dfsub.shape[0] == 0:
		return None
	#img,origin,spacing = load_itk_image(os.path.join(DATA_DIR, 'luna', 'imgs', patient  + '.mhd'))
	#print 'id',patient,'img shape',img.shape,'origin',origin,'spacing',spacing

	#now pick out VOXEL_SIZE mm of pixels in each dimension.
	# zoom = np.random.uniform(.97,1.03)
	numZpix = (np.round(np.random.uniform(.97,1.03) *float(VOXEL_SIZE) / spacing[0]))
	# assert numZpix > 10, 'too few z pixels'
	numYpix = (np.round(np.random.uniform(.97,1.03) *float(VOXEL_SIZE) / spacing[1]))
	# assert numYpix > 10, 'too few y pixels'
	numXpix = (np.round(np.random.uniform(.97,1.03) *float(VOXEL_SIZE) / spacing[2]))
	# assert numXpix > 10, 'too few x pixels'
	
	
	voxels = []
	indices = []
	for i in range(n):
	
		#choose a random nodule from this patient
		row = dfsub.iloc[ np.random.choice(dfsub.shape[0]) ]
		coords = (row['coordZ'], row['coordY'], row['coordX'])
		diameter_mm = row['diameter_mm']
		
		voxel_coords = worldToVoxelCoord(coords, origin, spacing)
		voxel_coords = np.round(voxel_coords)
		
		#fuzz 
		max_z_fuzz = int((numZpix/2) * (1 - diameter_mm / VOXEL_SIZE))
		max_y_fuzz = int((numYpix/2) * (1 - diameter_mm / VOXEL_SIZE))
		max_x_fuzz = int((numXpix/2) * (1 - diameter_mm / VOXEL_SIZE))
		zfuzz = np.random.randint(-max_z_fuzz, max_z_fuzz+1) if max_z_fuzz > 0 else 0
		yfuzz = np.random.randint(-max_y_fuzz, max_y_fuzz+1) if max_y_fuzz > 0  else 0
		xfuzz = np.random.randint(-max_x_fuzz, max_x_fuzz+1) if max_x_fuzz > 0 else 0


		z_start = np.clip(voxel_coords[0] + zfuzz - numZpix/2, 0, img.shape[0]).astype('int32')
		z_end = np.clip(voxel_coords[0] + zfuzz +numZpix/2, 0, img.shape[0]).astype('int32')
		y_start = np.clip(voxel_coords[1]+ yfuzz -numYpix/2, 0, img.shape[1]).astype('int32')
		y_end = np.clip(voxel_coords[1] + yfuzz +numYpix/2, 0, img.shape[1]).astype('int32')
		x_start = np.clip(voxel_coords[2]+xfuzz-numXpix/2, 0, img.shape[2]).astype('int32')
		x_end = np.clip(voxel_coords[2]+xfuzz +numXpix/2, 0, img.shape[2]).astype('int32')
			
		#now let's see if this voxel contains more than one nodule
		num_nodules = 0
		maxdiam_ix = -1
		maxdiam = 0
		for j in range(dfsub.shape[0]):
			row_j = dfsub.iloc[j]
			row_coords = (row_j['coordZ'], row_j['coordY'], row_j['coordX'])
			row_voxel_coords = worldToVoxelCoord(row_coords, origin, spacing)
			
			if (row_voxel_coords[2] > x_start+0 and row_voxel_coords[2] < x_end-0) and \
				(row_voxel_coords[1] > y_start+0 and row_voxel_coords[1] < y_end-0) and \
				(row_voxel_coords[0] > z_start+0 and row_voxel_coords[0] < z_end-0):
				
				#found one
				num_nodules += 1
				if row_j['diameter_mm'] > maxdiam:
					maxdiam_ix = row_j['ix']
					maxdiam = row_j['diameter_mm']
		
		if num_nodules == 0:
			# print 'no nodules in region!'
			# print x_start, x_end, y_start, y_end, z_start, z_end
			# print voxel_coords
			maxdiam_ix = -1
			
		# assert num_nodules > 0, 'no nodules in region'
		# if num_nodules > 1:
			# print 'multiple nodules found in voxel. choosing largest'
			
		indices.append(maxdiam_ix)
		
		voxel = img[z_start:z_end,y_start:y_end,x_start:x_end]
		
	
		# print voxel.shape, spacing
		voxel_norm = resize_voxel(voxel, (VOXEL_SIZE, VOXEL_SIZE, VOXEL_SIZE))
		if rotate and np.random.randint(0, 3) == 0:
			voxel_norm = ndimage.interpolation.rotate(voxel_norm, np.random.uniform(-10, 10), axes=(1,0), order=1,reshape=False,cval=-1000,mode='nearest')
			voxel_norm = ndimage.interpolation.rotate(voxel_norm, np.random.uniform(-10, 10), axes=(2,1), order=1,reshape=False,cval=-1000,mode='nearest')

		# halfsize = size/2
		voxel_norm = np.clip(voxel_norm, -1000, 400)
		voxel_norm = np.transpose(voxel_norm, (2,1,0)) #X,Y,Z 
		voxels.append(voxel_norm)
		
	return np.stack(voxels), np.array(indices).astype('int32')

def sample_random_candidates(id, df, n_sample,VOXEL_SIZE, dfcandidates,img, origin, spacing,rotate=True):
	#choose random voxels from this id,
	#if they contain a nodule, return the index of this nodule in the dataframe
	#from that we can determine size, attributes
	#TODO: TRIM IMAGE
	fp_only=True
	df['ix'] = range(df.shape[0])
	dfcandidates = dfcandidates[dfcandidates['seriesuid'] == id]
	dfsub = df[df['seriesuid']==id]
	nodule_coords = []
	nodule_sizes = []
	nodule_ixs = []
	
	if len(dfsub) > 0:
		for i in range(dfsub.shape[0]):
			row = dfsub.iloc[i]
			nodule_coords.append((row['coordZ'], row['coordY'], row['coordX']))
			nodule_sizes.append(row['diameter_mm'])
			
			
	#img,origin,spacing = load_itk_image(os.path.join(DATA_DIR, 'luna', 'imgs', id  + '.mhd'))
	voxel_coords = [worldToVoxelCoord(c,origin,spacing) for c in nodule_coords]
	

	# zoom = np.random.uniform(.97,1.03)
	numZpix = (np.round(np.random.uniform(.97,1.03) *float(VOXEL_SIZE) / spacing[0]))
	# assert numZpix > 10, 'too few z pixels'
	numYpix = (np.round(np.random.uniform(.97,1.03) *float(VOXEL_SIZE) / spacing[1]))
	# assert numYpix > 10, 'too few y pixels'
	numXpix = (np.round(np.random.uniform(.97,1.03) *float(VOXEL_SIZE) / spacing[2]))
	# assert numXpix > 10, 'too few x pixels'
	
	voxels = []
	ixs = []
	for i in range(n_sample):

		#choose a random row from the candidates file
		#OR choose a random voxel. 50-50.
		
		if dfcandidates.shape[0] > 0 and (np.random.randint(0,2) == 0 or fp_only):
			row = dfcandidates.iloc[np.random.choice(dfcandidates.shape[0])]
			x_center_raw = row['coordX'] * np.random.uniform(.9,1.1)
			y_center_raw = row['coordY'] * np.random.uniform(.9,1.1)
			z_center_raw = row['coordZ'] * np.random.uniform(.9,1.1)
			vcords = worldToVoxelCoord((z_center_raw, y_center_raw, x_center_raw), origin, spacing)
			x_center = vcords[2]
			y_center = vcords[1]
			z_center = vcords[0]
			ix = -2
			#now - if the coordinates are too close to an edge just default to random ones
			if x_center < numXpix/2 or x_center > img.shape[2]-numXpix/2 or \
				y_center < numYpix/2 or y_center > img.shape[1]-numYpix/2 or \
				z_center < numZpix/2 or z_center > img.shape[0]-numZpix/2:
				x_center = np.random.randint(low=numXpix/2,high=img.shape[2]-numXpix/2)
				y_center = np.random.randint(low=numYpix/2,high=img.shape[1]-numYpix/2)
				z_center = np.random.randint(low=numZpix/2,high=img.shape[0]-numZpix/2)
				ix = -1
		else:
			#print 'no candidates for id', id
			x_center = np.random.randint(low=numXpix/2,high=img.shape[2]-numXpix/2)
			y_center = np.random.randint(low=numYpix/2,high=img.shape[1]-numYpix/2)
			z_center = np.random.randint(low=numZpix/2,high=img.shape[0]-numZpix/2)
			ix = -1
			
		z_start = np.clip(z_center-numZpix/2, 0, img.shape[0]).astype('int32')
		z_end = np.clip(z_center+numZpix/2, 0, img.shape[0]).astype('int32')
		y_start = np.clip(y_center-numYpix/2, 0, img.shape[1]).astype('int32')
		y_end = np.clip(y_center+numYpix/2, 0, img.shape[1]).astype('int32')
		x_start = np.clip(x_center-numXpix/2, 0, img.shape[2]).astype('int32')
		x_end = np.clip(x_center+numXpix/2, 0, img.shape[2]).astype('int32')

		voxel = img[z_start:z_end,y_start:y_end,x_start:x_end]

		voxel_norm = resize_voxel(voxel, (VOXEL_SIZE, VOXEL_SIZE, VOXEL_SIZE))

		voxel_norm = np.clip(voxel_norm, -1000, 400)
		if rotate and np.random.randint(0, 3) == 0:
			voxel_norm = ndimage.interpolation.rotate(voxel_norm, np.random.uniform(-10, 10), axes=(1,0), order=1,reshape=False,cval=-1000,mode='nearest')
			voxel_norm = ndimage.interpolation.rotate(voxel_norm, np.random.uniform(-10, 10), axes=(2,1), order=1,reshape=False,cval=-1000,mode='nearest')

		#apply a random rotation
		
		#determine index (if applicable)
		#if no match put -1.
		largest_diam = 0
		for i,(coord,size) in enumerate(zip(voxel_coords,nodule_sizes)):
			if (x_start  < coord[2] < x_end) and (y_start < coord[1] < y_end ) and (z_start < coord[0] < z_end):
				#we got one
				if dfsub.iloc[i]['diameter_mm'] > largest_diam:
					largest_diam = dfsub.iloc[i]['diameter_mm']
					ix = dfsub.iloc[i]['ix']
				#target = size
		voxels.append(np.transpose(voxel_norm, (2,1,0)))
		ixs.append(ix)
		
	return np.stack(voxels),np.stack(ixs)
	
def get_data(df, ix):
	return df.iloc[ix]


def get_Xpositive_new(VOXEL_SIZE):
	df = pd.read_csv(os.path.join(DATA_DIR, "annotations_enhanced.csv"))
	all_luna_ids = [f.replace('.mhd', '') for f in os.listdir(LUNA_IMG_DIR) if '.mhd' in f]
	n_views = np.around(12*(64)/(VOXEL_SIZE))
	args = [(id,df,n_views) for id in all_luna_ids]
	results = Parallel(n_jobs=2,verbose=0)(delayed(get_bounding_voxels_new)(arg[0], arg[1],arg[2],VOXEL_SIZE,True) for arg in args )
	
	#results is a list of (voxels, ixs)
	voxels = np.concatenate([r[0] for r in results if r is not None])
	ixs = np.concatenate([r[1] for r in results if r is not None])
	np.save(os.path.join(DATA_DIR, 'Xpositive_temp_v5_' + str(VOXEL_SIZE) + '.npy'), voxels)
	np.save(os.path.join(DATA_DIR, 'IXpositive_temp_v5_' + str(VOXEL_SIZE) + '.npy'), ixs)
	
	
def get_Xnegative_new(VOXEL_SIZE,multiplier=12,fp_only=True):
	df = pd.read_csv(os.path.join(DATA_DIR, 'annotations_enhanced.csv'))

	dfc = pd.read_csv(os.path.join(DATA_DIR, 'candidates_V2.csv'))
	n_views = np.around(multiplier*(64)/(VOXEL_SIZE))
	all_luna_ids = [f.replace('.mhd', '') for f in os.listdir(LUNA_IMG_DIR) if '.mhd' in f]
	# args = [(id,df,30) for id in all_luna_ids]
	results = Parallel(n_jobs=2,verbose=0)(delayed(sample_random_candidates)(id, df, n_views,VOXEL_SIZE,dfc,fp_only,True) for id in all_luna_ids )
	#results is a list of (voxels, ixs)
	voxels = np.concatenate([r[0] for r in results])
	ixs = np.concatenate([r[1] for r in results])
	np.save(os.path.join(DATA_DIR, 'Xrandom_temp_v5_' + str(VOXEL_SIZE) + '.npy'), voxels)
	np.save(os.path.join(DATA_DIR, 'IXrandom_temp_v5_' + str(VOXEL_SIZE) + '.npy'), ixs)

def get_both(VOXEL_SIZE, n_neg, n_pos):
     	df = pd.read_csv(os.path.join(DATA_DIR, "annotations_enhanced.csv"))
	all_luna_ids = [f.replace('.mhd', '') for f in os.listdir(LUNA_IMG_DIR) if '.mhd' in f]
	n_views_pos = np.around(n_pos*(64)/(VOXEL_SIZE))
	#read all luna files
        #objs = []
        dfc = pd.read_csv(os.path.join(DATA_DIR, 'candidates_V2.csv'))
        n_views_neg = np.around(n_pos*(64)/(VOXEL_SIZE))
        #for id in all_luna_ids:
        #    objs.append(   load_itk_image(os.path.join(DATA_DIR, 'luna', 'imgs', id  + '.mhd')))

        #now we only have to do the reads once.

        #TODO: add parallelism
        posresults = []
        negresults = []
        for patient in all_luna_ids:
                img, origin, spacing = load_itk_image(os.path.join(DATA_DIR, 'luna', 'imgs', patient + '.mhd'))
                posresults.append( get_bounding_voxels_new(patient, df, n_views_pos, VOXEL_SIZE, img, origin, spacing, rotate=True))
                negresults.append( sample_random_candidates(patient, df, n_views_neg, VOXEL_SIZE, dfc, img, origin, spacing, rotate=True))

        voxels = np.concatenate([r[0] for r in posresults if r is not None])
	ixs = np.concatenate([r[1] for r in posresults if r is not None])
	np.save(os.path.join(DATA_DIR, 'Xpositive_temp_v5_' + str(VOXEL_SIZE) + '.npy'), voxels)
	np.save(os.path.join(DATA_DIR, 'IXpositive_temp_v5_' + str(VOXEL_SIZE) + '.npy'), ixs)


	voxels = np.concatenate([r[0] for r in negresults])
	ixs = np.concatenate([r[1] for r in negresults])
	np.save(os.path.join(DATA_DIR, 'Xrandom_temp_v5_' + str(VOXEL_SIZE) + '.npy'), voxels)
	np.save(os.path.join(DATA_DIR, 'IXrandom_temp_v5_' + str(VOXEL_SIZE) + '.npy'), ixs)
        return

LUNA_IMG_DIR = r'/home/ec2-user/data/luna/imgs'
DATA_DIR = r'/home/ec2-user/data'
 	
def main(stage,rs):
	np.random.seed(rs)
        import os
	get_both(stage, n_neg=3,n_pos=12)
	exit()
	
