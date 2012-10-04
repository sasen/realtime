import cherrypy
from mako.template import Template
from mako.lookup import TemplateLookup
from mako import exceptions
import subprocess
import os
import time
from library import makeSession, SUBJS, load_json, save_json, createSubDir
import library as lib
from json_template import json
import numpy as np
lookup = TemplateLookup(directories=['.','../cherrypy'],filesystem_checks=True,encoding_errors='replace',strict_undefined=True)

class MakoRoot:
    def __init__(self):
        self.history = "<ul><li>logged in</li></ul>"
        self.json = json
        self.TabID = 99
        self.jsonpath = ""

    def index(self):
        lijson = {"time":time.ctime(),
                  # "loginbox":[{"name":"subject","prompt":"Subject:"},
                  #             {"name":"visit","prompt":"Visit #:"} ] 
                  }
        try:
            loginTmpl = lookup.get_template("login.html")
            return loginTmpl.render(**lijson)
        except:
            return exceptions.html_error_template().render()
    index.exposed = True

    def doMakoLogin(self,subject=None,visit=None):
        self.jsonpath = os.path.join(SUBJS,subject,"%s_experiment_info.json"%subject)
        if os.path.exists(self.jsonpath):
            self.json = load_json(self.jsonpath)
        else:
            self.json = json
            self.json['subject_id'] = subject 
        self.json['time'] = time.ctime() ## record new login time
        visit = [v['active'] for v in self.json['Protocol']].index(True)  # auto-get last open tab
        ### if no sessiondir exists, create it 
        if not os.path.exists(os.path.join(SUBJS,subject)):
            self.history = createSubDir(subject) + self.history
        if not os.path.exists(os.path.join(SUBJS,"%s/session%s/"%(subject,visit))):
            history = makeSession(subject,visit)   # returns history
            self.history = history + self.history
        self.setTab(visit)          # activates the tab
        return self.renderAndSave()   # saves the json, and renders the page
    doMakoLogin.exposed = True

    def renderAndSave(self):
        #self.completionChecks()   # activates the next relevant button
        save_json(self.jsonpath,self.json)
        try:
            subregTmpl = lookup.get_template("subreg.html")
            return subregTmpl.render(**self.json)
        except:
            return exceptions.html_error_template().render()
    renderAndSave.exposed=True

    def timeStamp(self,progIndex):  ## store time in epoch-secs + string
        tStamp = "%f"%time.time()  ## get time in seconds in the epoch
        timeReadable = time.strftime("%H:%M:%S--%m/%d/%Y",time.localtime(float(tStamp)))
        self.json['Protocol'][self.TabID]['Steps'][progIndex]['history'].append(tStamp)
        self.json['Protocol'][self.TabID]['Steps'][progIndex]['time'] = timeReadable
        return  ### end timeStamp

    def getTimeStamp(self,prog):
        if isinstance(prog,int):  ## RT run, add runNum to json lookup for rt runs 
            index = self.json['rtLookup'] + (prog - 1)
        elif isinstance(prog,str):  ## not an RT run 
            index = self.json[prog]
        return self.json['Protocol'][self.TabID]['Steps'][index]['time']
    getTimeStamp.exposed = True

    def clearTimeStamp(self,prog):  ### clear nonRT timestamps only
        self.json['Protocol'][self.TabID]['Steps'][self.json[prog]]['time'] = ""
        return
    clearTimeStamp.exposed = True


    def makoCheckboxHandler(self,action,program,checked,progIndex):
        # checkboxes should be enabled one at a time.
        # checkboxes should have timestamps collected
        self.timeStamp(progIndex)
        ## toggle its status from unchecked to checked, etc...
        self.json['Protocol'][self.TabID]['Steps'][progIndex]['checked'] = not self.json['Protocol'][self.TabID]['Steps'][progIndex]['checked']
        ## disable once checked, enable next step if it's a checkbox
        if self.json['Protocol'][self.TabID]['Steps'][progIndex]['checked']:
            self.json['Protocol'][self.TabID]['Steps'][progIndex]['disabled'] = True
            if self.json['Protocol'][self.TabID]['Steps'][progIndex+1]['text'][0:7] == action:
                self.json['Protocol'][self.TabID]['Steps'][progIndex+1]['disabled'] = False
        return
    makoCheckboxHandler.exposed = True

    def formHandler(self,button):
        Dict = self.locate(button)
        if Dict["ui"]=="button":
            exec(Dict["action"])
        if Dict["ui"]=="checkbox":
            Dict["checked"] = not Dict["checked"]
        Dict["clicked"] = True
        self.eval_click(Dict)
        self.set_all_dicts(self.json["Protocol"])
        return self.renderAndSave()

    formHandler.exposed=True

    def eval_click(self,Dict):
        lists = Dict["on_click"].split(" , ")
        print lists
        for dicts in lists:
            key, item = dicts.split(" = ")
            Dict[key] = eval(item)

    def setdict(self,Dict):
        if not Dict["ui"] == "loop":
            if not Dict["enabled_when"] == None:
                print Dict["text"]
                Dict["disabled"] = not self.eval_bool(Dict["enabled_when"])
        else:
            self.set_all_dicts(Dict["Steps"])

    def set_all_dicts(self,Dict):
        for D in Dict:
            self.setdict(D)

    def eval_bool(self,phrase):
        c = []
        coords = phrase.replace("and","")
        coords = coords.replace("or","")
        coords = coords.replace("(","")
        coords = coords.replace(")","")
        coords = coords.replace("not","")
        coords = coords.replace("!","").replace("  ", " ").replace("  "," ")
        c = coords.split(" ")
        for loc in c:
            print loc
            D = self.locate(loc)
            phrase = phrase.replace(loc,str(D["clicked"]))
        print "phrase = ", phrase
        return eval(phrase)    

    def locate(self,coord):
        coords = coord.split('.')
        coords = np.asarray(coords).astype(int).tolist()
        x = lambda P, l: P[l]
        step = lambda P: P["Steps"]
        Protocol = self.json["Protocol"]
        P = Protocol
        for i,c in enumerate(coords):
            P = x(P,c)
            if i == len(coords)-1:
                return P
            else:
                P = step(P)

    def setSuiteState(self,suite,state):
        ## GOAL: in this tab, enable/disable all steps of a certain suite.
        ## -- suites: "Test", "Acquire","Launch","[Re]Start" (action keywords)
        ## -- -- except "RT Run" to access Redo Run buttons
        ## -- uses human readable states ("disabled", "enabled","reset")
        tab = self.TabID
        stepNames = [st['text'] for st in self.json['Protocol'][tab]['Steps']]  ## get all step names
        for n,name in enumerate(stepNames):
            args = name.split(' ')  # [action, program] or ['RT','Run']
            if args[0] == suite: # does the step action match the suite name?
                print "trying to %s %s"%(state, name)
                self.setButtonState(name,state)
                # if (suite == "Test") and (state == disable):                    
            elif name == suite:   ## RT Run
                self.setButtonState("Redo Run %d"%(n+1-self.json['rtLookup']),state)  ## inverse of runIndex computations elsewhere
        return
    setSuiteState.exposed = True
        
    def completionChecks(self):
        tab = self.TabID
        print self.json.keys()
        lastVisit = self.json["rtVisits"]+1   # only +1 because 0-indexed
        ##### Enable tab only if prev visit complete AND this visit incomplete 
        ### BUG: final localizer's tests are stuck enabled!
        if tab > 0:            
            if self.json['Protocol'][tab-1]['complete'] and (not self.json['Protocol'][tab]['complete']): 
                ## BUG: unless we're in the middle of running something?
                self.setSuiteState('Test','enabled') ## activate tests on this tab
                self.setSuiteState('Acquire','enabled')
            else:
                self.setSuiteState('Test','disabled') ## deactivate tests on this tab?
                self.setSuiteState('Acquire','disabled')
        ##### Create lists of Tests and Functional Scans
        # -- Based on tab, we can handle funcloc and rt runs differently.
        # -- checkList: tests should be done before any anatomical / functional runs.
        # -- funcList: functional/task scans, in sequential order
        # -- funcRoot + visitType: strings to help us handle RT runs differently
        if (tab == 0) or (tab == lastVisit):  # funcloc
            checkList = ['Display','Buttons','Trigger','BirdSounds','LetterSounds']   ## need to add scans / get programatically?
            funcList = ['1-back-localizer','1-back-transfer','2-back-transfer']  ## autoget?
            funcRoot = ""
            visitType = ""
        elif (tab > 0) and (tab < lastVisit): # rt visit
            checkList = ['Display','Buttons','Trigger']   ## eventually need to add scan Runs // get programatically?
            funcList = range(1,(self.json["runsPerRtVisit"]+1))
            funcRoot = "Murfi "
            visitType = "RT"
        ####### Ensure all pre-tests in checkList are complete (have timestamps)
        # -- list comprehension to get length of timestamp
        # -- any 0-length timestamps are incomplete. using count(0) to find them.
        emptyStamps = [len(self.getTimeStamp(test)) for test in checkList].count(0)  
        if emptyStamps == 0:
            ####### Determine progress through functional scan list in funcList
            # -- now the count of 0-length timestamps tells us how many scans are left
            # -- use scansLeft as a negative index into funcList to get name of next scan
            # -- rt runs need "Murfi" added to the runNum to produce next scan name
            # -- enable button for next scan via the scan name we just produced
            scansLeft = [len(self.getTimeStamp(scan)) for scan in funcList].count(0)
            ## BUG: 0-length doesn't work after redos.... is that OK?
            if scansLeft == 0: ## visit complete!
                self.json['Protocol'][tab]['complete'] = True 
                self.setButtonState('Complete %sVisit'%visitType,'enabled')
                self.setSuiteState('Test','disabled')
            else:
                nextScan = funcRoot + str(funcList[-scansLeft])
                self.setButtonState('null %s'%nextScan,'enabled')
        return   ## end def completionChecks()
    completionChecks.exposed=True
    
    def makoDoNBack(self,program):
        self.setButtonState("Launch %s"%program,"disabled")
        return 
    makoDoNBack.exposed = True

    def makoDoMurfi(self,action):
        run = self.run
        if (action == "End"):
            ## call endMurfi
            ## attach RT run timestamp to End Murfi
            runIndex = self.json['rtLookup'] + (run - 1)  # run is 1-indexed, so subtract 1
            self.timeStamp(runIndex)
#            tStamp = time.ctime()
            # tStamp = "%f"%time.time()
            # self.json['Protocol'][self.TabID]['Steps'][runIndex]['time'] = tStamp
            # self.json['Protocol'][self.TabID]['Steps'][runIndex]['history'].append(tStamp)
            self.setButtonState("null Murfi %d"%run,"disabled")
            self.setButtonState("null Serve %d"%run,"disabled")
            self.setButtonState("null RT %d"%run,"disabled")
            self.setButtonState("Redo Run %d"%run,"enabled")
            if (run < self.json["runsPerRtVisit"]):
                self.setButtonState("null Murfi %d"%(run+1),"enabled")
        else:
            ## call doMurfi here
            self.setButtonState("null Serve %d"%run,"enabled")
            self.setButtonState("null RT %d"%run,"enabled")
        return
    makoDoMurfi.exposed = True

    def makoDoServe(self,action):
        run = self.run
        if (action == "End"):
            ## call endServe
            self.setButtonState("null Murfi %d"%run,"enabled")
        else:
            ## call doServe
            self.setButtonState("null Murfi %d"%run,"disabled")
            return
        makoDoServe.exposed = True

    def makoRedoRun(self):  ## disable the redo button + next action, enable relevant actions
        self.setButtonState("Redo Run %d"%self.run,"disabled")
        ### BUG: actually, all other Redos and all other starts should be disabled
        if self.run < self.json['runsPerRtVisit']:
        ### BUG: couldn't get this to work in an RT visit
            self.setButtonState("null Murfi %d"%(self.run+1),"disabled")                
        self.setButtonState("Restart Murfi %d"%self.run,"enabled")
        return
    makoRedoRun.exposed = True

    def makoRedoVisit(self,prog):  ## disable the redo button + next action, enable relevant actions
        self.setButtonState("Redo %s"%prog,"disabled")
        self.buttonReuse("Redo %s -"%prog)
        self.json['Protocol'][self.TabID]['complete'] = False
        self.setSuiteState('Test','reset')  ## reactivate tests on this tab
        self.setSuiteState('Acquire','reset')  ## reactivate structurals on this tab
        ### BUG: fails to reactivate functional scans
        return
    makoRedoVisit.exposed = True
    
    def setTab(self,tab):
        self.TabID = int(tab)
        if self.TabID > len(self.json['Protocol']):  ## visit must be defined in Protocol
            self.TabID = 0
        for (i,v) in enumerate(self.json['Protocol']):
            if i==self.TabID:
                v['active'] = True
            else:
                v['active'] = False
        return self.renderAndSave()
    setTab.exposed=True

    def buttonReuse(self,button):
        ## When a button has been pressed, (say to start something),
        ## rename it to the opposite function (say, to end the thing)
        [act,prog,runNum] = button.split(' ')
        if (act == "Start") or (act == "Restart"):
            newText = "End %s"%prog
        elif act == "End":
            newText = "Restart %s"%prog  
        elif act == "Complete":
            self.json['Protocol'][self.TabID]['Steps'][self.json[prog]]['text'] = "Redo %s"%prog
            return
        elif act == "Redo":
            self.json['Protocol'][self.TabID]['Steps'][self.json[prog]]['text'] = "Complete %s"%prog
            return
        else:    ## not startable/endable
            return
        runIndex = self.json['rtLookup'] + (int(runNum) - 1)  # runNum is 1-indexed, so subtract 1
        self.json['Protocol'][self.TabID]['Steps'][runIndex]['Steps'][self.json[prog]]["text"] = newText
        return
    buttonReuse.exposed = True

    def setButtonState(self,button,state):
        ## goal: changes the value of a button's disabled value in the json.
        ## -- allows the use of "disabled" or "enabled", rather than T/F
        ## -- "reset" is a state that means "enabled", and clears the timestamp to allow Redo
        if state == "disabled":
            stateBool = True
        elif (state == "enabled") or (state == "reset"):
            stateBool = False
        btnArgs = button.split(' ')  # button could have 2 or 3 arguments
        if len(btnArgs) == 2: 
            [act,prog] = btnArgs
            try:
                progIndex = self.json[prog]
            except:
                progIndex = prog
            if state == "reset":   ## only tests and funcloc scans can be reset
                self.clearTimeStamp(prog)
            self.json['Protocol'][self.TabID]['Steps'][self.json[prog]]['disabled'] = stateBool
        elif len(btnArgs) == 3:
            [act,prog,run] = btnArgs
            runIndex = self.json['rtLookup'] + (int(run) - 1)  # run is 1-indexed, so subtract 1
            self.json['Protocol'][self.TabID]['Steps'][runIndex]['Steps'][self.json[prog]]['disabled'] = stateBool
        return
    setButtonState.exposed = True

if __name__ == "__main__":
    if (os.getlogin() == 'ss'):    ### sasen will use different port
        cherrypy.config.update({'server.socket_host': '18.93.5.27',
                                'server.socket_port': 8090
                                })
    config = {'/': {'tools.staticdir.on': True,
                    'tools.staticdir.dir': os.getcwd()},
              '/css': {'tools.staticdir.on': True,
                       'tools.staticdir.dir': os.path.abspath('css/')},
              '/js': {'tools.staticdir.on': True, 
                      'tools.staticdir.dir':os.path.abspath('js/')},
              '/flot': {'tools.staticdir.on': True,
                        'tools.staticdir.dir': os.path.abspath('../flot')},
              '/img': {'tools.staticdir.on': True, 
                      'tools.staticdir.dir':os.path.abspath('img/')}
              }
    cherrypy.tree.mount(MakoRoot(),'/',config=config)
    cherrypy.engine.start()
    cherrypy.engine.block()