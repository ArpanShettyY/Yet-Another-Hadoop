import sys
import rpyc
from rpyc.utils.server import ThreadedServer
import json
import os
import pickle
import logging
import signal
import uuid
import random
import time

#python namenode.py its_port config_path
myPort = int(sys.argv[1])
fdata=open(sys.argv[2],"r")
config=json.load(fdata)
fdata.close()


#setting up logger
import logging.config
logging.basicConfig(filename=config['namenode_log_path'], level=logging.INFO, format='%(asctime)s: %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p')
logger = logging.getLogger('')
logger.info("Namenode Started")

fs_image = {
    'folders': {

    },
    'files': {

    }
}

tempBlockDetails = {}

#for each datanode, maintains num of available blocks {datanode_id: availableNum}
datanodeDetails = {}
datanodePorts = {}

#loading saved fs_image back to memory
checkpointFilePath = os.path.join(config['namenode_checkpoints'], "checkpointFile")
if os.path.exists(checkpointFilePath):
    try:
        with open(checkpointFilePath, 'rb') as f:
            fs_image = pickle.load(f)
        logger.info("fs_image loaded from checkpoint")
        logger.info(fs_image)
    except:
        logger.error("Error loading fs_image checkpoint")

class NameNodeService(rpyc.Service):
    def exposed_isReady(self):
        return True
    def exposed_registerDatanode(self, id, portNum, availableNum):
        datanodeDetails[id] = availableNum
        datanodePorts[id] = portNum
        logger.info("Datanode %s registered", id)
        return True

    def exposed_returnPorts(self, id):
        return datanodePorts[id]

    def getFolder(self, absoluteFolderPath): #returns folder dict if exists, else return false
        curFolder = fs_image
        splitPath = list(filter(lambda x: x, absoluteFolderPath.split("/")))
        for folderName in splitPath:
            if not folderName.isalnum():
                return False
            if folderName in curFolder["folders"].keys():
                curFolder = curFolder["folders"][folderName]
            else:
                return False
        return curFolder
    
    def exposed_getFolder(self, absoluteFolderPath):
        folder=self.getFolder(absoluteFolderPath)
        folder_names=[]
        for i in folder.keys():
            folder_names.append(folder.values())
        return folder_names

    def exposed_isFolderExists(self, absoluteFolderPath): #path: separated by / ex: a/b/c
        if self.getFolder(absoluteFolderPath):
            return True
        else: return False

    def getFile(self, absoluteFilePath): #returns file if exists, else return false
        splitPath = list(filter(lambda x: x, absoluteFilePath.split("/")))
        fileName = splitPath[-1]
        folderPath = splitPath[:-1]
        if self.exposed_isFolderExists(str("/").join(folderPath)):
            curFolder = self.getFolder(str("/").join(folderPath))
            if fileName in curFolder["files"].keys():
                return curFolder['files'][fileName]
            else:
                return False
        return False

    def exposed_getFile(self,absoluteFilePath):
        return self.getFile(absoluteFilePath)
    
    def exposed_isFileExists(self, absoluteFilePath): #path: a/b/c/file.txt
        if self.getFile(absoluteFilePath):
            return True
        else: return False

    def exposed_addFolder(self, absoluteFolderPath): #adds a new folder for absoluteFolderPath, return true or false
        splitPath = list(filter(lambda x: x, absoluteFolderPath.split("/")))
        folderName = splitPath[-1]
        if not folderName.isalnum():
            return False
        parentFolderPath = str("/").join(splitPath[:-1])
        folder = self.getFolder(parentFolderPath)
        if folder == False:
            return False
        if folderName in folder['folders'].keys():
            return False
        #adding entry
        folder["folders"][folderName] = {
            "folders": {},
            "files": {},
            "metadata": {
                'createdTime': time.time()
            }
        }
        logger.info("Added new Folder {}".format(absoluteFolderPath))
        return True

    def exposed_addFileEntry(self, absoluteFilePath, meta): #adds file entry, return true. Else return false
        meta = pickle.loads(meta) #objects must be passed as pickled, to preserve their type
        if self.exposed_isFileExists(absoluteFilePath):
            return False
        splitPath = list(filter(lambda x: x, absoluteFilePath.split("/")))
        fileName = splitPath[-1]
        folderPath = splitPath[:-1]
        folder = self.getFolder(str("/").join(folderPath))
        #adding entry
        folder['files'][fileName] = {
            "metadata": meta,
            "blocks": []
        }
        logger.info("Added new file {} ".format(absoluteFilePath))
        return True

    def exposed_allocateBlocks(self):
        randId = uuid.uuid1().int
        #for now, allocating datanodes randomly
        #as of now, I'm not checking if space available or not, will add it later
        n = config['replication_factor']
        rowToSend = [randId] #with port numbers of datanodes
        rowToStore = [randId] #with id of datanodes
        available = {i for i in datanodeDetails.keys()} #later may add other variable called as active datanodes and use it
        for i in range(n):
            ch = random.choice(list(available))
            rowToStore.append(ch)
            available.remove(ch)
            rowToSend.append(datanodePorts[ch])
            # datanodeDetails[ch] -= 1
            #not changing, availableNum as of now, will do later
        tempBlockDetails[randId] = rowToStore
        return rowToSend
        
    def exposed_commitBlocks(self, block_id, status, absoluteFilePath=''):
        #might improve later
        if not status:
            tempBlockDetails.pop(block_id)
            return
        row = tempBlockDetails.pop(block_id)
        file = self.getFile(absoluteFilePath)
        file['blocks'].append(row)
        return

def writeCheckPoints(signal, frame): #writes fs_image into checkpointFile
    with open(checkpointFilePath, 'wb') as f:
        pickle.dump(fs_image, f)
        logger.info("Fs_image written into Checkpoint")
    sys.exit()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, writeCheckPoints)
    t = ThreadedServer(NameNodeService, port=myPort)
    logger.info("Namenode ThreadedServer started on port %s", myPort)
    t.start()



