(function (exports, Laya) {
    'use strict';

    var TrailVS = "#define SHADER_NAME TrailVS\n#include \"Camera.glsl\";\n#include \"Scene.glsl\"\n#include \"SceneFogInput.glsl\"\n#include \"TrailVertexUtil.glsl\"\nvoid main(){float normalizeTime=(u_CurTime-a_BirthTime)/u_LifeTime;v_Texcoord0=vec2(a_Texcoord0X,1.0-a_Texcoord0Y)*u_TilingOffset.xy+u_TilingOffset.zw;v_Color=a_Color;vec3 cameraPos=(u_View*a_position).rgb;gl_Position=u_Projection*vec4(cameraPos+a_OffsetVector*getCurWidth(normalizeTime),1.0);gl_Position=remapPositionZ(gl_Position);\n#ifdef FOG\nFogHandle(gl_Position.z);\n#endif\n}";

    var TrailFS = "#define SHADER_NAME TrailFS\n#include \"Color.glsl\";\n#include \"Scene.glsl\";\n#include \"SceneFog.glsl\";\nvarying vec2 v_Texcoord0;varying vec4 v_Color;void main(){vec4 color=2.0*u_MainColor*v_Color;\n#ifdef MAINTEXTURE\nvec4 mainTextureColor=texture2D(u_MainTexture,v_Texcoord0);\n#ifdef Gamma_u_MainTexture\nmainTextureColor=gammaToLinear(mainTextureColor);\n#endif\ncolor*=mainTextureColor;\n#endif\n#ifdef FOG\ncolor.xyz=scenUnlitFog(color.xyz);\n#endif\ngl_FragColor=color;gl_FragColor=outputTransform(gl_FragColor);}";

    class TrailShaderInit {
        static init() {
            Laya.TrailShaderCommon.init();
            let shader = Laya.Shader3D.add("Trail", false, false);
            shader.shaderType = Laya.ShaderFeatureType.Effect;
            let subShader = new Laya.SubShader(Laya.TrailShaderCommon.attributeMap, Laya.TrailShaderCommon.uniformMap, Laya.TrailShaderCommon.defaultValue);
            shader.addSubShader(subShader);
            subShader.addShaderPass(TrailVS, TrailFS);
            TrailMaterial.defaultMaterial = new TrailMaterial();
            TrailMaterial.defaultMaterial.lock = true;
        }
    }

    class TrailMaterial extends Laya.Material {
        static __initDefine__() {
            TrailMaterial.MAINTEXTURE = Laya.Shader3D.propertyNameToID("u_MainTexture");
            TrailMaterial.TINTCOLOR = Laya.Shader3D.propertyNameToID("u_MainColor");
            TrailMaterial.TILINGOFFSET = Laya.Shader3D.propertyNameToID("u_TilingOffset");
            TrailShaderInit.init();
        }
        get color() {
            return this._shaderValues.getColor(TrailMaterial.TINTCOLOR);
        }
        set color(value) {
            this._shaderValues.setColor(TrailMaterial.TINTCOLOR, value);
        }
        get texture() {
            return this._shaderValues.getTexture(TrailMaterial.MAINTEXTURE);
        }
        set texture(value) {
            if (value)
                this._shaderValues.addDefine(TrailMaterial.SHADERDEFINE_MAINTEXTURE);
            else
                this._shaderValues.removeDefine(TrailMaterial.SHADERDEFINE_MAINTEXTURE);
            this._shaderValues.setTexture(TrailMaterial.MAINTEXTURE, value);
        }
        get tilingOffset() {
            return this._shaderValues.getVector(TrailMaterial.TILINGOFFSET);
        }
        set tilingOffset(value) {
            if (value) {
                this._shaderValues.setVector(TrailMaterial.TILINGOFFSET, value);
            }
            else {
                this._shaderValues.getVector(TrailMaterial.TILINGOFFSET).setValue(1.0, 1.0, 0.0, 0.0);
            }
        }
        constructor() {
            super();
            this.setShaderName("Trail");
            this.materialRenderMode = Laya.MaterialRenderMode.RENDERMODE_ALPHABLENDED;
        }
        clone() {
            var dest = new TrailMaterial();
            this.cloneTo(dest);
            return dest;
        }
        set renderMode(value) {
            switch (value) {
                case TrailMaterial.RENDERMODE_ADDTIVE:
                    this.renderQueue = Laya.Material.RENDERQUEUE_TRANSPARENT;
                    this.depthWrite = false;
                    this.cull = Laya.RenderState.CULL_NONE;
                    this.blend = Laya.RenderState.BLEND_ENABLE_ALL;
                    this.blendSrc = Laya.RenderState.BLENDPARAM_SRC_ALPHA;
                    this.blendDst = Laya.RenderState.BLENDPARAM_ONE;
                    this.alphaTest = false;
                    this._shaderValues.addDefine(TrailMaterial.SHADERDEFINE_ADDTIVEFOG);
                    break;
                case TrailMaterial.RENDERMODE_ALPHABLENDED:
                    this.renderQueue = Laya.Material.RENDERQUEUE_TRANSPARENT;
                    this.depthWrite = false;
                    this.cull = Laya.RenderState.CULL_NONE;
                    this.blend = Laya.RenderState.BLEND_ENABLE_ALL;
                    this.blendSrc = Laya.RenderState.BLENDPARAM_SRC_ALPHA;
                    this.blendDst = Laya.RenderState.BLENDPARAM_ONE_MINUS_SRC_ALPHA;
                    this.alphaTest = false;
                    this._shaderValues.removeDefine(TrailMaterial.SHADERDEFINE_ADDTIVEFOG);
                    break;
                default:
                    throw new Error("renderMode value error: " + value);
            }
        }
    }
    TrailMaterial.RENDERMODE_ALPHABLENDED = 0;
    TrailMaterial.RENDERMODE_ADDTIVE = 1;
    Laya.Laya.addAfterInitCallback(() => {
        if (!TrailMaterial.defaultMaterial) {
            TrailMaterial.__initDefine__();
        }
    });

    exports.TrailAlignment = void 0;
    (function (TrailAlignment) {
        TrailAlignment[TrailAlignment["View"] = 0] = "View";
        TrailAlignment[TrailAlignment["TransformZ"] = 1] = "TransformZ";
    })(exports.TrailAlignment || (exports.TrailAlignment = {}));
    class TrailFilter extends Laya.TrailBaseFilter {
        constructor(owner) {
            super(owner._baseRenderNode.shaderData);
            this.alignment = exports.TrailAlignment.View;
            this._ownerRender = owner;
            this.addRenderElement();
        }
        addRenderElement() {
            var render = this._ownerRender;
            var elements = render._renderElements;
            var material = render.sharedMaterials[0];
            (material) || (material = TrailMaterial.defaultMaterial);
            var element = new Laya.RenderElement();
            element.setTransform(this._ownerRender.owner._transform);
            element.render = render;
            element.material = material;
            element._renderElementOBJ.geometry = this._trialGeometry._geometryElementOBj;
            elements.push(element);
        }
        _update(state) {
            var render = this._ownerRender;
            const scene = this._ownerRender.owner.scene;
            if (!scene)
                return;
            this._curtime += Math.min(scene.timer.delta / 1000, 0.016);
            render._baseRenderNode.shaderData.setNumber(Laya.TrailShaderCommon.CURTIME, this._curtime);
            var curPos = this._ownerRender.owner.transform.position;
            this._trialGeometry._updateDisappear(this._curtime, this._time);
            if (!Laya.Vector3.equals(this._lastPosition, curPos)) {
                if ((this._trialGeometry._endIndex - this._trialGeometry._activeIndex) === 0) {
                    this._trialGeometry._addTrailByFirstPosition(curPos, this._curtime);
                }
                else {
                    var delVector3 = Laya.TrailGeometry._tempVector36;
                    var pointAtoBVector3 = Laya.TrailGeometry._tempVector35;
                    switch (this.alignment) {
                        case exports.TrailAlignment.View:
                            var cameraMatrix = state.camera.viewMatrix;
                            Laya.Vector3.transformCoordinate(curPos, cameraMatrix, Laya.TrailGeometry._tempVector33);
                            Laya.Vector3.transformCoordinate(this._trialGeometry._lastFixedVertexPosition, cameraMatrix, Laya.TrailGeometry._tempVector34);
                            Laya.Vector3.subtract(Laya.TrailGeometry._tempVector33, Laya.TrailGeometry._tempVector34, delVector3);
                            pointAtoBVector3.x = -delVector3.y;
                            pointAtoBVector3.y = delVector3.x;
                            pointAtoBVector3.z = 0;
                            break;
                        case exports.TrailAlignment.TransformZ:
                            Laya.Vector3.subtract(curPos, this._trialGeometry._lastFixedVertexPosition, delVector3);
                            var forward = Laya.TrailGeometry._tempVector33;
                            this._ownerRender.owner.transform.getForward(forward);
                            Laya.Vector3.cross(delVector3, forward, pointAtoBVector3);
                            break;
                    }
                    Laya.Vector3.normalize(pointAtoBVector3, pointAtoBVector3);
                    Laya.Vector3.scale(pointAtoBVector3, this._widthMultiplier / 2, pointAtoBVector3);
                    var delLength = Laya.Vector3.scalarLength(delVector3);
                    this._trialGeometry._addTrailByNextPosition(curPos, this._curtime, this._minVertexDistance, pointAtoBVector3, delLength);
                }
            }
            this._trialGeometry._updateVertexBufferUV(this._colorGradient, this._textureMode);
            curPos.cloneTo(this._lastPosition);
            if (this._trialGeometry._disappearBoundsMode) {
                var bounds = this._ownerRender.bounds;
                var min, max;
                var sprite3dPosition = this._ownerRender.owner.transform.position;
                bounds.setMin(sprite3dPosition);
                bounds.setMax(sprite3dPosition);
                min = bounds.getMin();
                max = bounds.getMax();
                let _vertices1 = this._trialGeometry._vertices1;
                for (var i = this._trialGeometry._activeIndex; i < this._trialGeometry._endIndex; i++) {
                    var posOffset = this._trialGeometry._floatCountPerVertices1 * 2 * i;
                    var pos = Laya.TrailGeometry._tempVector35;
                    var up = Laya.TrailGeometry._tempVector33;
                    var side = Laya.TrailGeometry._tempVector34;
                    pos.setValue(_vertices1[posOffset + 0], _vertices1[posOffset + 1], _vertices1[posOffset + 2]);
                    up.setValue(_vertices1[posOffset + 3], _vertices1[posOffset + 4], _vertices1[posOffset + 5]);
                    Laya.Vector3.add(pos, up, side);
                    Laya.Vector3.min(side, min, min);
                    Laya.Vector3.max(side, max, max);
                    Laya.Vector3.subtract(pos, up, side);
                    Laya.Vector3.min(side, min, min);
                    Laya.Vector3.max(side, max, max);
                }
                bounds.setMin(min);
                bounds.setMax(max);
                this._trialGeometry._disappearBoundsMode = false;
            }
            this._trialGeometry._updateRenderParams();
        }
    }

    class TrailRenderer extends Laya.BaseRender {
        constructor() {
            super();
        }
        _isMaterialVaild(value) {
            return value.checkType(Laya.ShaderFeatureType.Effect);
        }
        _getcommonUniformMap() {
            return ["Sprite3D", "TrailRender"];
        }
        _createBaseRenderNode() {
            return Laya.Laya3DRender.Render3DModuleDataFactory.createMeshRenderNode();
        }
        _onAdded() {
            super._onAdded();
            this._trailFilter = new TrailFilter(this);
            this._setRenderElements();
        }
        get time() {
            return this._trailFilter.time;
        }
        set time(value) {
            this._trailFilter.time = value;
        }
        get minVertexDistance() {
            return this._trailFilter.minVertexDistance;
        }
        set minVertexDistance(value) {
            this._trailFilter.minVertexDistance = value;
        }
        get widthMultiplier() {
            return this._trailFilter.widthMultiplier;
        }
        set widthMultiplier(value) {
            this._trailFilter.widthMultiplier = value;
        }
        get widthCurve() {
            return this._trailFilter.widthCurve;
        }
        set widthCurve(value) {
            this._trailFilter.widthCurve = value;
        }
        get colorGradient() {
            return this._trailFilter.colorGradient;
        }
        set colorGradient(value) {
            this._trailFilter.colorGradient = value;
        }
        get textureMode() {
            return this._trailFilter.textureMode;
        }
        set textureMode(value) {
            this._trailFilter.textureMode = value;
        }
        get alignment() {
            return this._trailFilter.alignment;
        }
        set alignment(value) {
            this._trailFilter.alignment = value;
        }
        _onEnable() {
            super._onEnable();
            this.owner._transform.position.cloneTo(this._trailFilter._lastPosition);
        }
        renderUpdate(context) {
            this._calculateBoundingBox();
            this._renderElements.forEach((element, index) => {
                var _a, _b;
                element._geometry;
                element._renderElementOBJ.isRender = this._trailFilter._isRender();
                let material = (_a = this.sharedMaterial) !== null && _a !== void 0 ? _a : TrailMaterial.defaultMaterial;
                material = (_b = this.sharedMaterials[index]) !== null && _b !== void 0 ? _b : material;
                element.material = material;
                element._renderElementOBJ.materialRenderQueue = material.renderQueue;
            });
        }
        get bounds() {
            return this._bounds;
        }
        _calculateBoundingBox() {
            let context = Laya.RenderContext3D._instance;
            this.boundsChange = false;
            this._trailFilter._update(context);
        }
        clear() {
            this._trailFilter.clear();
        }
        _onDestroy() {
            this._trailFilter.destroy();
            super._onDestroy();
        }
        _cloneTo(dest) {
            super._cloneTo(dest);
            dest.time = this.time;
            dest.minVertexDistance = this.minVertexDistance;
            var widthCurve = [];
            var widthCurveData = this.widthCurve;
            for (let i = 0, n = this.widthCurve.length; i < n; i++) {
                widthCurve.push(widthCurveData[i].clone());
            }
            dest.widthCurve = widthCurve;
            dest.colorGradient = this.colorGradient.clone();
            dest.textureMode = this.textureMode;
            dest.alignment = this.alignment;
        }
    }

    let c = Laya.ClassUtils.regClass;
    c("TrailFilter", TrailFilter);
    c("TrailRenderer", TrailRenderer);
    c("TrailMaterial", TrailMaterial);

    exports.TrailFilter = TrailFilter;
    exports.TrailMaterial = TrailMaterial;
    exports.TrailRenderer = TrailRenderer;
    exports.TrailShaderInit = TrailShaderInit;

})(window.Laya = window.Laya || {}, Laya);
//# sourceMappingURL=laya.trail3D.js.map
