import * as THREE from 'three/webgpu';
import type { SpatialDestination } from './spatialWorkspaceModel';

type Builder = {
  box:(w:number,h:number,d:number,m:THREE.Material,p:THREE.Object3D,x?:number,y?:number,z?:number,r?:number)=>THREE.Mesh;
  mesh:(g:THREE.BufferGeometry,m:THREE.Material,p:THREE.Object3D,x?:number,y?:number,z?:number)=>THREE.Mesh;
  white:THREE.Material; silver:THREE.Material; dark:THREE.Material;
  glass:THREE.Material; accent:THREE.Material; amber:THREE.Material;
};

/** Procedural architectural models. All resources belong to the renderer's
 * disposal registry. These are navigation metaphors, not live system telemetry.
 */
export function buildPavilion(id:SpatialDestination,parent:THREE.Group,b:Builder) {
  const {box,mesh,white,silver,dark,glass,accent,amber}=b;
  box(1.9,.16,1.8,white,parent,0,-.28,0,.12);
  box(1.78,.035,1.68,silver,parent,0,-.18,0,.07);
  // A continuous category foundation connects each room to the shared app.
  box(1.64,.13,1.52,accent,parent,0,-.10,0,.06);
  for(const x of [-.65,.65])box(.06,.04,.28,dark,parent,x,-.38,.58,.012);

  if(id==='demo'){
    // An inhabited application: three floors, glazing, service bays and a core.
    for(let level=0;level<3;level++){
      const y=.18+level*.42;
      box(1.58,.11,1.42,accent,parent,0,y,0,.055);
      box(1.42,.055,1.3,white,parent,0,y+.075,0,.028);
      for(const x of [-.63,.63])box(.035,.3,1.2,glass,parent,x,y+.23,0,.008);
      for(let i=0;i<4;i++){
        box(.21,.18,.16,i===level?accent:dark,parent,-.45+i*.3,y+.20,.42,.016);
        box(.12,.015,.012,silver,parent,-.45+i*.3,y+.22,.51,.003);
      }
    }
    for(const x of [-.72,.72])for(const z of [-.60,.60])box(.045,1.45,.045,silver,parent,x,.64,z,.009);
    box(.42,1.58,.40,silver,parent,-.48,.64,-.45,.03);
    for(let i=0;i<8;i++)box(.29,.026,.015,dark,parent,-.48,.15+i*.14,-.235,.004);
    box(1.36,.04,1.24,glass,parent,.02,1.36,0,.025);
    box(.65,.07,.55,white,parent,.27,1.43,.17,.03);
    box(.42,.055,.33,accent,parent,.27,1.49,.17,.025);
  }else if(id==='journey'){
    // Intake room: a machined open slot, real sheets and a collection tray.
    box(1.24,.85,.85,accent,parent,0,.38,-.1,.08);
    box(1.06,.065,.90,white,parent,0,.84,-.1,.035);
    box(.88,.19,.045,dark,parent,0,.60,.35,.03);
    box(.88,.20,.52,silver,parent,0,.17,.49,.035);
    box(.76,.025,.48,white,parent,0,.29,.56,.018);
    for(let i=0;i<4;i++){
      const sheet=box(.65,.025,.43,i===3?amber:white,parent,.025*i,.32+i*.045,.59-i*.015,.012);
      sheet.rotation.y=-.035*i;
    }
    for(let i=0;i<3;i++)box(.045,.045,.015,white,parent,-.36+i*.13,.38,.335,.008);
    box(.18,.35,.12,silver,parent,.70,.14,.35,.025);
    box(.14,.12,.015,glass,parent,.70,.30,.42,.01);
  }else if(id==='access'){
    // A controlled entrance, rather than a padlock icon. Three glazed lanes.
    for(const x of [-.57,0,.57]){
      for(const z of [-.4,.4]){
        box(.12,.72,.14,silver,parent,x,.28,z,.025);
        box(.09,.055,.10,accent,parent,x,.67,z,.014);
      }
      box(.025,.62,.70,glass,parent,x,.35,0,.008);
    }
    box(1.45,.07,.16,accent,parent,0,.77,-.4,.025);
    for(const x of [-.29,.29]){
      box(.20,.045,.20,accent,parent,x,.02,.56,.04);
      mesh(new THREE.CylinderGeometry(.075,.075,.22,16),white,parent,x,.16,.56);
      mesh(new THREE.SphereGeometry(.075,16,12),silver,parent,x,.34,.56);
    }
    box(.29,.08,.30,white,parent,.7,.17,.53,.025);
    const reader=box(.24,.29,.045,dark,parent,.7,.36,.54,.025);reader.rotation.x=-.22;
    box(.12,.015,.012,accent,parent,.7,.39,.573,.003);
  }else if(id==='engineering'){
    // A review bench with paired source windows and a physical diff stack.
    box(1.5,.09,.86,white,parent,0,.40,0,.045);
    for(const x of [-.61,.61])box(.075,.56,.65,silver,parent,x,.08,0,.025);
    for(const x of [-.36,.36]){
      box(.61,.45,.065,silver,parent,x,.76,-.22,.03);
      box(.54,.35,.015,dark,parent,x,.77,-.178,.015);
      for(let i=0;i<4;i++)box(.20+(i%2)*.17,.012,.01,i===1?accent:white,parent,x-.035,.87-i*.058,-.166,.003);
      box(.045,.12,.045,silver,parent,x,.50,-.22,.008);
    }
    box(.49,.015,.22,dark,parent,-.29,.46,.17,.02);
    for(let i=0;i<3;i++){
      const diff=box(.44,.035,.34,i===2?accent:white,parent,.38,.48+i*.055,.22,.02);
      diff.rotation.y=-.10+i*.1;
    }
    box(.16,.20,.27,dark,parent,-.70,.58,-.22,.025);
  }else{
    // Repeated needs become a structured model, without inventing any metrics.
    for(let x=0;x<3;x++)for(let z=0;z<2;z++){
      const height=.18+((x+z*2)%3)*.18;
      box(.32,height,.32,x===1?accent:white,parent,(x-1)*.46,height/2+.04,(z-.5)*.55,.035);
      box(.23,.025,.23,silver,parent,(x-1)*.46,height+.06,(z-.5)*.55,.025);
    }
    for(const x of [-.7,.7])box(.035,.8,.035,silver,parent,x,.42,-.55,.008);
    box(1.42,.035,.035,silver,parent,0,.83,-.55,.008);
    box(1.23,.55,.025,glass,parent,0,.55,-.55,.012);
    for(let i=0;i<4;i++)box(.16,.02,.014,accent,parent,-.44+i*.28,.44+i%2*.15,-.53,.004);
  }
}
