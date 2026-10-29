import * as THREE from 'three/webgpu';
import { builtinAOContext, mrt, normalView, pass, screenUV } from 'three/tsl';
import { ao } from 'three/addons/tsl/display/GTAONode.js';

/** Contact shading for physical depth. This pass has no application state. */
export function createStudioLighting(renderer:THREE.WebGPURenderer,scene:THREE.Scene,camera:THREE.Camera) {
  // GTAO gathers adjacent depth samples. A multisampled depth texture cannot be
  // gathered in WGSL; keep this prepass single-sample even when the scene uses MSAA.
  const normalPass=pass(scene,camera,{samples:0});
  normalPass.setMRT(mrt({output:normalView}));
  const occlusion=ao(normalPass.getTextureNode('depth'),normalPass.getTextureNode(),camera);
  occlusion.resolutionScale=.5;
  occlusion.samples.value=8;
  occlusion.radius.value=.3;
  occlusion.thickness.value=.65;
  occlusion.scale.value=.7;
  const scenePass=pass(scene,camera);
  scenePass.contextNode=builtinAOContext(occlusion.getTextureNode().sample(screenUV).r);
  const pipeline=new THREE.RenderPipeline(renderer);
  pipeline.outputNode=scenePass;
  return {
    render(){const tone=renderer.toneMapping,space=renderer.outputColorSpace;try{pipeline.render();}finally{renderer.toneMapping=tone;renderer.outputColorSpace=space;}},
    dispose(){pipeline.dispose();normalPass.dispose();scenePass.dispose();occlusion.dispose();},
  };
}
