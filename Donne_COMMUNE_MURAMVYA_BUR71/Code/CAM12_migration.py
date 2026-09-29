"""
Model exported as python.
Name : Migration
Group : NGA03
With QGIS : 31604
"""


from qgis.core import QgsProcessing
from qgis.core import QgsProcessingAlgorithm
from qgis.core import QgsProcessingMultiStepFeedback
from qgis.core import QgsProcessingParameterString
from qgis.core import QgsProcessingParameterVectorLayer
from qgis.core import QgsProcessingParameterBoolean
from qgis.core import QgsProcessingParameterNumber
from qgis.core import QgsProcessingParameterFeatureSink
from qgis.core import QgsProcessingParameterDefinition
import processing
from qgis.core import QgsVectorLayer
import processing



class Zefze(QgsProcessingAlgorithm):
    
    def initAlgorithm(self, config=None):
        #introduction des variables et inputs
        param = QgsProcessingParameterString('dP', 'dP', optional=True, multiLine=False, defaultValue='dP')
        self.addParameter(QgsProcessingParameterVectorLayer('Pixelpop', 'Pixelpop', defaultValue=None))
        self.addParameter(QgsProcessingParameterBoolean('VERBOSE_LOG', 'Verbose logging', optional=True, defaultValue=False))
        self.addParameter(QgsProcessingParameterFeatureSink('Upop', 'Upop', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Opop', 'OPOP', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testa', 'TESTA', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testb', 'TESTB', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testc', 'TESTC', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testd', 'TESTD', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Teste', 'TESTE', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testf', 'TESTF', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testg', 'TESTG', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testh', 'TESTH', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testi', 'TESTI', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testj', 'TESTJ', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testk', 'TESTK', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testl', 'TESTL', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testm', 'TESTM', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testn', 'TESTN', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testo', 'TESTO', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testp', 'TESTP', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Testq', 'TESTQ', type=QgsProcessing.TypeVectorPoint, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Test25', 'test25', type=QgsProcessing.TypeVectorAnyGeometry, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterFeatureSink('Pixel_temp', 'Pixel_temp', type=QgsProcessing.TypeVectorAnyGeometry, createByDefault=True, supportsAppend=True, defaultValue=None))
        #self.addParameter(QgsProcessingParameterFeatureSink('Testf2', 'testF2', type=QgsProcessing.TypeVectorAnyGeometry, createByDefault=True, supportsAppend=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterString('Year', 'Year', multiLine=False, defaultValue=''))
        
    def processAlgorithm(self, parameters, context, model_feedback):
        # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
        # overall progress through the model
        feedback = QgsProcessingMultiStepFeedback(21, model_feedback)
        results = {}
        outputs = {}
        
        
        Year_model = parameters['Year']
        #Dossier de travail
        pathx='C:/Users/LGI/Desktop/SHER CONSULT/PROJECT/BUR71/GIS/BUR71_Data/'+Year_model+'/'
        #pathx='C:/Users/Keyvan/Documents/Project/OUG05/Tech/Pop/Output_pop_model/'+Year_model+'/'
        Pixel=parameters['Pixelpop']
        #itérateurs
        j=1
        Nbrep=0
        
        
        # Population_initiale_year X stored in memory
        alg_params = {
            'FIELD_LENGTH': 0,
            'FIELD_NAME': 'P'+str(Year_model)+'m',
            'FIELD_PRECISION': 0,
            'FIELD_TYPE': 2,
            'FORMULA': 'P'+str(Year_model)+'value', # doit donc lire le nom de la colonne de population existante. 
            'INPUT': Pixel,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            }
        outputs['P_mem'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        results['Testf'] = outputs['P_mem']['OUTPUT']
        
        print('P'+str(Year_model)+'m')
        
        # D_work -> création de la colonne de travail de l'algorihm
        alg_params = {
            'FIELD_LENGTH': 0,
            'FIELD_NAME': 'P_sum',
            'FIELD_PRECISION': 0,
            'FIELD_TYPE': 0,
            'FORMULA': 'P'+str(Year_model)+'m',
            'INPUT': outputs['P_mem']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            }
        outputs['D_work'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        results['Testc'] = outputs['D_work']['OUTPUT']
        
        Pixel=results['Testc']
        

       

        while(j>0):


            #Drop field(s), a personalisé selon les besoins
            alg_params = {
                'COLUMN': ['P2023value','P2025value','P2030value','P2035value','P2040value','P2045value','P2050value','P2055value','P2060value'],
                'INPUT': Pixel,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            }
            outputs['DropFields1'] = processing.run('qgis:deletecolumn', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            print(j)
               
            
            # dP_calc delta pop (pmax - p)
            alg_params = {
                'FIELD_LENGTH': 10,
                'FIELD_NAME': 'dP',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 1,
                'FORMULA': '\"Pmax\"-\"P_sum\"',
                'INPUT': outputs['DropFields1']['OUTPUT'],
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                'OUTPUT': pathx+'DP_Nbrep_'+str(Nbrep)
                
            }
            outputs['Dp_calc'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            #results['Testa'] = outputs['Dp_calc']['OUTPUT']
            
            feedback.setCurrentStep(2)
            if feedback.isCanceled():
                return {}

            # Select_Upop underpop, dP positif
            alg_params = {
                'FIELD': 'dP',
                'INPUT': outputs['Dp_calc']['OUTPUT'],
                'METHOD': 0,
                'OPERATOR': 2,
                'VALUE': '0'
            }
            outputs['Select_upop'] = processing.run('qgis:selectbyattribute', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

            feedback.setCurrentStep(3)
            if feedback.isCanceled():
                return {}

            # extract_upop
            alg_params = {
                'INPUT': outputs['Select_upop']['OUTPUT'],
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                'OUTPUT':pathx+'Testa'+str(j)
            }
            outputs['Extract_upop'] = processing.run('native:saveselectedfeatures', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

            feedback.setCurrentStep(4)
            if feedback.isCanceled():
                return {}

            # CentroidsUpop
            alg_params = {
                'ALL_PARTS': False,
                'INPUT': outputs['Extract_upop']['OUTPUT'],
                #'OUTPUT': parameters['Upop']
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                #'OUTPUT':pathx+'Upop_'+str(j)+'TestYAHO'
                'OUTPUT':pathx+'Testb'+str(j)              
            }
            outputs['Centroidsupop'] = processing.run('native:centroids', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            results['Testa'] = outputs['Centroidsupop']['OUTPUT']

            feedback.setCurrentStep(5)
            if feedback.isCanceled():
                return {}

            # Select_opop donc delta pop negatif
            alg_params = {
                'FIELD': 'dP',
                'INPUT': outputs['Select_upop']['OUTPUT'],
                'METHOD': 0,
                'OPERATOR': 4,
                'VALUE': '0'
            }
            outputs['Select_opop'] = processing.run('qgis:selectbyattribute', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

            feedback.setCurrentStep(6)
            if feedback.isCanceled():
                return {}

            # Extract_opop
            alg_params = {
                'INPUT': outputs['Select_opop']['OUTPUT'],
                'OUTPUT':pathx+'Testc'+str(j)
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            }
            outputs['Extract_opop'] = processing.run('native:saveselectedfeatures', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

            feedback.setCurrentStep(7)
            if feedback.isCanceled():
                return {}

            # CentroidsOpo
            alg_params = {
                'ALL_PARTS': False,
                'INPUT': outputs['Extract_opop']['OUTPUT'],
                #'OUTPUT': parameters['Opop']
                'OUTPUT':pathx+'Opop_'+str(j)
            }
            outputs['Centroidsopo'] = processing.run('native:centroids', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            results['Opop'] = outputs['Centroidsopo']['OUTPUT']
            Opop_layer = QgsVectorLayer(outputs['Centroidsopo']['OUTPUT'], "test_feature", "ogr") 
            
            
            if (Opop_layer.featureCount()<1): #countfeature in the shape
            #si n feature = 0 -> j=0 boucle stop
                j=0
                
            else :
                j=j+1
                
                
            #calcul le nombre d'itération
            Nbrep=Nbrep+1
            Nbfeatures = Opop_layer.featureCount()
            print(Nbfeatures)
           
            
            feedback.setCurrentStep(8)
            if feedback.isCanceled():
                return {}

            # Distance matrix
            alg_params = {
                'INPUT': outputs['Centroidsopo']['OUTPUT'],
                'INPUT_FIELD': 'id',
                'MATRIX_TYPE': 0,
                'NEAREST_POINTS': 3,
                'TARGET': outputs['Centroidsupop']['OUTPUT'],
                'TARGET_FIELD': 'id',
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                #'OUTPUT': parameters['Testa']
                'OUTPUT':pathx+'Testd'+str(j)
                
            }
            outputs['DistanceMatrix'] = processing.run('qgis:distancematrix', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            results['Testa'] = outputs['DistanceMatrix']['OUTPUT']

            feedback.setCurrentStep(9)
            if feedback.isCanceled():
                return {}

            # JoinUPOP
            alg_params = {
                'DISCARD_NONMATCHING': True,
                'FIELD': 'TargetID',
                'FIELDS_TO_COPY': [''],
                'FIELD_2': 'ID',
                'INPUT': outputs['DistanceMatrix']['OUTPUT'],
                'INPUT_2': outputs['Centroidsupop']['OUTPUT'],
                'METHOD': 0,
                'PREFIX': 'Upop_',
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                'OUTPUT':pathx+'Teste'+str(j)
            }
            outputs['Joinupop'] = processing.run('native:joinattributestable', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

            feedback.setCurrentStep(10)
            if feedback.isCanceled():
                return {}

            # Fix_join_upop
            alg_params = {
                'INPUT': outputs['Joinupop']['OUTPUT'],
                #'OUTPUT': parameters['Test25']
                'OUTPUT':pathx+'UpopJoin_'+str(j)
            }
            outputs['Fix_join_upop'] = processing.run('native:fixgeometries', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            results['Test25'] = outputs['Fix_join_upop']['OUTPUT']

            
            feedback.setCurrentStep(11)
            if feedback.isCanceled():
                return {}

            # JoinOpop
            alg_params = {
                'DISCARD_NONMATCHING': True,
                'FIELD': 'InputID',
                'FIELDS_TO_COPY': [''],
                'FIELD_2': 'ID',
                'INPUT': outputs['Fix_join_upop']['OUTPUT'],
                'INPUT_2': outputs['Centroidsopo']['OUTPUT'],
                'METHOD': 0,
                'PREFIX': 'Opop_',
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                'OUTPUT':pathx+'Testf'+str(j)
                #'OUTPUT': parameters['Testb']
            }
            outputs['Joinopop'] = processing.run('native:joinattributestable', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            #results['Testb'] = outputs['Joinopop']['OUTPUT']
            
            
            feedback.setCurrentStep(12)
            if feedback.isCanceled():
                return {}
            
            # Calc_pop_spreading2
            alg_params = {
                'FIELD_LENGTH': 10,
                'FIELD_NAME': 'NumSplit',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 1,
                'FORMULA': 'count(InputID,InputID)',
                'INPUT': outputs['Joinopop']['OUTPUT'],
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                'OUTPUT': pathx+'TestGAINpop1_'+str(j)
            }
            outputs['Calc_pop_spreading'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            
            # Calc_pop_spreading
            alg_params = {
                'FIELD_LENGTH': 10,
                'FIELD_NAME': 'Gain_pop',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 1,
                'FORMULA': 'Opop_dP / NumSplit',
                'INPUT': outputs['Calc_pop_spreading']['OUTPUT'],
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                'OUTPUT': pathx+'TestGAINpop2_'+str(j)
            }
            outputs['Calc_pop_spreading2'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
           

            
            # Calc_pop_spreading2
            alg_params = {
                'FIELD_LENGTH': 10,
                'FIELD_NAME': 'NumSplit_T',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 1,
                'FORMULA': 'count(TargetID,TargetID)',
                'INPUT': outputs['Calc_pop_spreading2']['OUTPUT'],
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                'OUTPUT': pathx+'TestGAINpop3_'+str(j)
            }
            outputs['Calc_pop_spreading3'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            
            # Calc_pop_spreading3
            alg_params = {
                'FIELD_LENGTH': 10,
                'FIELD_NAME': 'Gain_pop',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 1,
                'FORMULA': 'sum(Gain_pop,TargetID)',
                'INPUT': outputs['Calc_pop_spreading3']['OUTPUT'],
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                'OUTPUT': pathx+'TestGAINpop4_'+str(j)
            }
            outputs['Calc_pop_spreading4'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True) 
            
            # Calc_pop_spreading3
            alg_params = {
                'FIELD_LENGTH': 10,
                'FIELD_NAME': 'Gain_pop',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 1,
                'FORMULA': 'Gain_pop / 1',
                'INPUT': outputs['Calc_pop_spreading4']['OUTPUT'],
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                'OUTPUT': pathx+'TestGAINpop5_'+str(j)
            }
            outputs['Calc_pop_spreading5'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            
            #results['Testb'] = outputs['Calc_pop_spreading2']['OUTPUT']
            feedback.setCurrentStep(13)
            if feedback.isCanceled():
                return {}

            # DistanceMax
            alg_params = {
                'FIELD_LENGTH': 10000,
                'FIELD_NAME': 'Distance_max',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 1,
                'FORMULA': 'maximum(\"Distance\", \"TargetID\")',
                'INPUT': outputs['Calc_pop_spreading5']['OUTPUT'],
                'OUTPUT':pathx+'Testg'+str(j)
            }
            outputs['Distancemax'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

            feedback.setCurrentStep(14)
            if feedback.isCanceled():
                return {}

            # Join Dmax
            alg_params = {
                'DISCARD_NONMATCHING': False,
                'FIELD': 'id',
                'FIELDS_TO_COPY': [''],
                'FIELD_2': 'TargetID',
                'INPUT': outputs['Dp_calc']['OUTPUT'],
                'INPUT_2': outputs['Distancemax']['OUTPUT'],
                'METHOD': 1,
                'PREFIX': 'temp',
                'OUTPUT':pathx+'Testh'+str(j)
                #'OUTPUT':parameters['Testc']
            }
            outputs['JoinDmax'] = processing.run('native:joinattributestable', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            #results['Testc']=outputs['JoinDmax']['OUTPUT']
            
            feedback.setCurrentStep(15)
            if feedback.isCanceled():
                return {}

            # Join Bilan
            alg_params = {
                'DISCARD_NONMATCHING': False,
                'FIELD': 'id',
                'FIELDS_TO_COPY': [''],
                'FIELD_2': 'InputID',
                'INPUT': outputs['JoinDmax']['OUTPUT'],
                'INPUT_2': outputs['Joinopop']['OUTPUT'],
                'METHOD': 1,
                'PREFIX': '',
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                'OUTPUT':parameters['Testb']
            }
            outputs['JoinBilan'] = processing.run('native:joinattributestable', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            results['Testc']=outputs['JoinBilan']['OUTPUT']
            
            feedback.setCurrentStep(16)
            if feedback.isCanceled():
                return {}

            # Calc_pop_sum
            alg_params = {
                'FIELD_LENGTH': 10000,
                'FIELD_NAME': 'P_sum',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 1,
                'FORMULA': 'case \r\nwhen \"tempGain_pop\" is null then \"P_sum\"  else  \"P_sum\" + abs(\"tempGain_pop\") end',
                'INPUT': outputs['JoinBilan']['OUTPUT'],
                'OUTPUT':pathx+'Testi'+str(j)
                #'OUTPUT': parameters['Testd']
            }
            outputs['Calc_pop_sum'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

            feedback.setCurrentStep(17)
            if feedback.isCanceled():
                return {}

            # Maj_psum
            alg_params = {
                'FIELD_LENGTH': 100000,
                'FIELD_NAME': 'P_sum',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 1,
                'FORMULA': 'case \r\nwhen \"Opop_dP\" is not null then \r\n\"Pmax\" else \"P_sum\" end',
                'INPUT': outputs['Calc_pop_sum']['OUTPUT'],
                'OUTPUT':pathx+'Testj'+str(j)
                #'OUTPUT': parameters['Teste']
            }
            outputs['Maj_psum'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

            feedback.setCurrentStep(18)
            if feedback.isCanceled():
                return {}

            # P percentage
            alg_params = {
                'FIELD_LENGTH': 100000,
                'FIELD_NAME': 'P_sper',
                'FIELD_PRECISION': 3,
                'FIELD_TYPE': 0,
                'FORMULA': '\"P_sum\"/\"Pmax\"*100',
                'INPUT': outputs['Maj_psum']['OUTPUT'],
                'OUTPUT':pathx+'Testk'+str(j)
                
            }
            outputs['PPercentage'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            
            
            feedback.setCurrentStep(19)
            if feedback.isCanceled():
                return {}
            
            #Drop field(s)
            alg_params = {
                #'COLUMN': ['tempInputID','tempfid','fid','tempTargetID','tempDistance','tempUpop_P2022','tempUpop_fid','tempUpop_P_sper','tempUpop_Distance_max','tempOpop_P_sper','tempOpop_Distance_max','fid_2','Upop_fid','Upop_P_sper','Opop_P_sper','Opop_Distance_max','Upop_Distance_max','tempUpop_D2022_km2','tempUpop_Dmax','tempUpop_Q_L','tempUpop_ID','tempUpop_P_sum','tempUpop_dP','tempOpop_fid','tempOpop_P2022','tempOpop_D2022_km2','tempOpop_Dmax','tempOpop_Q_L','tempOpop_ID','tempOpop_P_sum','tempOpop_dP','tempGain_pop','tempDistance_max','InputID','TargetID','Distance','Upop_P2022','Upop_D2022_km2','Upop_Dmax','Upop_Q_L','Upop_ID','Upop_P_sum','Upop_dP','Opop_fid','Opop_P2022','Opop_D2022_km2','Opop_Dmax','Opop_Q_L','Opop_ID','Opop_P_sum','Opop_dP'],
                'COLUMN': ['tempInputID','tempfid','fid','tempUpop_P'+str(Year_model)+'m','tempOpop_P'+str(Year_model)+'m','Upop_P'+str(Year_model)+'m','Opop_P'+str(Year_model)+'m','temp'+str(Year_model)+'m','tempTargetID','tempNumSplit','tempNumSplit_T','tempDistance','tempUpop_P2022','tempUpop_fid','tempUpop_P_sper','tempUpop_Distance_max','tempOpop_P_sper','tempOpop_Distance_max','fid_2','Upop_fid','Upop_P_sper','Opop_P_sper','Opop_Distance_max','Upop_Distance_max','tempUpop_D2022_km2','tempUpop_Pmax','tempUpop_Q_fixed','tempUpop_ID','tempUpop_P_sum','tempUpop_dP','tempOpop_fid','tempOpop_P2022','tempOpop_D2022_km2','tempOpop_Pmax','tempOpop_Q_fixed','tempOpop_ID','tempOpop_P_sum','tempOpop_dP','tempGain_pop','tempDistance_max','InputID','TargetID','Distance','Upop_P2022','Upop_D2022_km2','Upop_Pmax','Upop_Q_fixed','Upop_ID','Upop_P_sum','Upop_dP','Opop_fid','Opop_P2022','Opop_D2022_km2','Opop_Pmax','Opop_Q_fixed','Opop_ID','Opop_P_sum','Opop_dP'],
                'INPUT': outputs['PPercentage']['OUTPUT'],
                'OUTPUT':pathx+'Testl'+str(j)
                #'OUTPUT': parameters['Testd']
            }
            outputs['DropFields'] = processing.run('qgis:deletecolumn', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            #results['Testd']=outputs['DropFields']['OUTPUT']
            
            feedback.setCurrentStep(20)
            if feedback.isCanceled():
                return {}
            
            # Dist_max_maj
            alg_params = {
                'FIELD_LENGTH': 100000,
                'FIELD_NAME': 'Distance_max',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 1,
                'FORMULA': 'case when \"Distance_max\" is null then \"tempDistance_max\" when \"Distance_max\" < \"tempDistance_max\"then \"tempDistance_max\"else \"Distance_max\" end',
                'INPUT': outputs['DropFields']['OUTPUT'],
                #'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                'OUTPUT': pathx+'Nbrep_'+str(Nbrep)+'Nbfeature_'+str(Nbfeatures)

            }
            outputs['Dist_max_maj'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
            results['Pixel_temp'] = outputs['Dist_max_maj']['OUTPUT']

            
            
            
            Pixel = results['Pixel_temp']
           
            
        return results

    def name(self):
        return 'OUG05_migration'

    def displayName(self):
        return 'OUG05_migration'

    def group(self):
        return 'OUG05'

    def groupId(self):
        return 'OUG05'

    def createInstance(self):
        return Zefze()
