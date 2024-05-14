import subprocess
import os

import numpy as np


# 生成一个 0 到 1 之间的伪随机序列
# can't work in mac system

class RQMCGenerator(object):

    SavedValue = {}

    @staticmethod
    def AddToSavedValue(nrpoints, dimensionpoint, a):
        RQMCGenerator.SavedValue["%s_%s"%(nrpoints,dimensionpoint)] = a

    @staticmethod
    def GetFromSavedValue(nrpoints, dimensionpoint):
        key = "%s_%s" % (nrpoints, dimensionpoint)
        if key in  RQMCGenerator.SavedValue:
            return RQMCGenerator.SavedValue[key]
        else:
            return None

    # This method generate a set of points in [0,1] using RQMC. The points are generated with the library given
    # on the website of P. Lecuyer
    @staticmethod
    def RQMC01(nrpoints, dimensionpoint, withweight=True, QMC=False):
        randomizer = [0] * dimensionpoint
        if not QMC:
            randomizer = [np.random.uniform(0.0, 10000000.0) for i in range(dimensionpoint)]

        a = RQMCGenerator.GetFromSavedValue(nrpoints, dimensionpoint)
        if a is None:
            weight = "product:1:1"
            if withweight:
                weight = "product:0.1:0.1"
            # reurn the array given by the library
            cmd = 'latbuilder --lattice-type "ordinary" --size "%d" --dimension "%d" --norm-type "2" --figure-of-merit "CU:P2" --construction "CBC" --weights "%s" --weights-power "1"' \
                  % (nrpoints, dimensionpoint, weight)

            if not os.name == 'nt':
                cmd = './' + cmd
            result = subprocess.check_output(cmd, shell=True) # Run command with cmd arguments and return its output if no error.
            restable = result.split(b"lattice", 10000)
            restable2 = restable[len(restable) - 1].split(b"[", 10000)
            restable3 = restable2[1].split(b"]", 10000)
            resaslistofstring = restable3[0].split(b',')
            a = [float(ai) for ai in resaslistofstring] # 生成一个随机序列
            # print(a)
            # print(randomizer)
            # print(min(randomizer[d] for d in range(dimensionpoint))) # 有些代码怪怪的
            RQMCGenerator.AddToSavedValue(nrpoints, dimensionpoint, a)

        result = [[(i * a[d] % nrpoints) / float(nrpoints) for d in range(dimensionpoint)] for i
                  in range(nrpoints)]

        result = [[(((i * a[d] % nrpoints) / float(nrpoints)) + randomizer[d]) % 1.0 for d in range(dimensionpoint)] for i
                  in range(nrpoints)] # 看来是两种生成序列的方式，第二种还加了个伪随机数

        # print(result)
        return result
        
    

# test
# RQMCGenerator.RQMC01(10, 5)