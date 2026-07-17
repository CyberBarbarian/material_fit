(function (exports, Laya) {
    'use strict';

    class RenderCullUtil {
        static cullByCameraCullInfo(cameraCullInfo, list, count, opaqueList, transparent, context) {
            const boundFrustum = cameraCullInfo.boundFrustum;
            const cullMask = cameraCullInfo.cullingMask;
            const staticMask = cameraCullInfo.staticMask;
            let render;
            let canPass;
            for (let i = 0; i < count; i++) {
                render = list[i];
                canPass = ((1 << render.layer) & cullMask) != 0 && (render.renderbitFlag == 0);
                canPass = canPass && ((render.staticMask & staticMask) != 0);
                if (canPass) {
                    if (!cameraCullInfo.useOcclusionCulling || render._needRender(boundFrustum)) {
                        let distance = render.distanceForSort = Laya.Vector3.distanceSquared(render.bounds._imp.getCenter(), cameraCullInfo.position);
                        if (render.visibalRangeBit == 0 || (distance > render.visibalMin && distance < render.visibalMax)) {
                            render._renderUpdatePre(context);
                            let element;
                            const elements = render.renderelements;
                            for (let j = 0, len = elements.length; j < len; j++) {
                                element = elements[j];
                                if (element.materialRenderQueue > 2500)
                                    transparent.addRenderElement(element);
                                else
                                    opaqueList.addRenderElement(element);
                            }
                        }
                    }
                }
            }
        }
        static cullDirectLightShadow(shadowCullInfo, list, count, opaqueList, context) {
            opaqueList.clear();
            for (let i = 0; i < count; i++) {
                const render = list[i];
                if (render.shadowCullPass()) {
                    if (Laya.FrustumCulling.cullingRenderBounds(render.bounds, shadowCullInfo)) {
                        let distance = render.distanceForSort = Laya.Vector3.distanceSquared(render.bounds._imp.getCenter(), shadowCullInfo.cameraPosition);
                        if (render.visibalRangeBit == 0 || (distance > render.visibalMin && distance < render.visibalMax)) {
                            render._renderUpdatePre(context);
                            let element;
                            const elements = render.renderelements;
                            for (let j = 0, len = elements.length; j < len; j++) {
                                element = elements[j];
                                if (element.materialRenderQueue < 2500)
                                    opaqueList.addRenderElement(element);
                            }
                        }
                    }
                }
            }
        }
        static cullSpotShadow(cameraCullInfo, list, count, opaqueList, context) {
            opaqueList.clear();
            const boundFrustum = cameraCullInfo.boundFrustum;
            for (let i = 0; i < count; i++) {
                const render = list[i];
                render._renderUpdatePre(context);
                if (render.shadowCullPass()) {
                    let distance = render.distanceForSort = Laya.Vector3.distanceSquared(render.bounds._imp.getCenter(), cameraCullInfo.position);
                    if (render.visibalRangeBit == 0 || (distance > render.visibalMin && distance < render.visibalMax)) {
                        if (render._needRender(boundFrustum)) {
                            let element;
                            const elements = render.renderelements;
                            for (let j = 0, len = elements.length; j < len; j++) {
                                element = elements[j];
                                if (element.materialRenderQueue < 2500)
                                    opaqueList.addRenderElement(element);
                            }
                        }
                    }
                }
            }
        }
    }

    class RenderQuickSort {
        sort(elements, isTransparent, left, right) {
            this.elementArray = elements;
            this.isTransparent = isTransparent;
            this._quickSort(left, right);
        }
        _quickSort(left, right) {
            if (this.elementArray.length > 1) {
                const index = this._partitionRenderObject(left, right);
                const leftIndex = index - 1;
                if (left < leftIndex)
                    this._quickSort(left, leftIndex);
                if (index < right)
                    this._quickSort(index, right);
            }
        }
        _partitionRenderObject(left, right) {
            const elements = this.elementArray.elements;
            const pivot = elements[Math.floor((right + left) / 2)];
            while (left <= right) {
                while (this._compare(elements[left], pivot) < 0)
                    left++;
                while (this._compare(elements[right], pivot) > 0)
                    right--;
                if (left < right) {
                    const temp = elements[left];
                    elements[left] = elements[right];
                    elements[right] = temp;
                    left++;
                    right--;
                }
                else if (left === right) {
                    left++;
                    break;
                }
            }
            return left;
        }
        _compare(left, right) {
            const renderQueue = left.materialRenderQueue - right.materialRenderQueue;
            if (renderQueue === 0) {
                const sort = this.isTransparent ? right.owner.distanceForSort - left.owner.distanceForSort : left.owner.distanceForSort - right.owner.distanceForSort;
                return sort + right.owner.sortingFudge - left.owner.sortingFudge;
            }
            else
                return renderQueue;
        }
    }

    class RenderListQueue {
        get elements() { return this._elements; }
        constructor(isTransParent) {
            this._elements = new Laya.FastSinglelist();
            this.batchModule = new Laya.SingletonList();
            this._isTransparent = isTransParent;
            this._quickSort = new RenderQuickSort();
        }
        addRenderElement(renderelement) {
            renderelement.materialShaderData && this._elements.add(renderelement);
        }
        addBatchAgent(agent) {
            this.batchModule.add(agent);
        }
        renderQueue(context) {
            this.sort();
            if (!this._isTransparent && this.batchModule.length > 0) {
                for (var i = 0, n = this.batchModule.length; i < n; i++) {
                    let list = this.batchModule.elements[i].opaqueList;
                    for (var j = 0, m = list.length; j < m; j++) {
                        let elements = list.elements;
                        this._elements.add(elements[j]);
                    }
                }
            }
            context.drawRenderElementList(this._elements);
            Laya.LayaGL.statAgent.recordCTData(this._isTransparent ? Laya.StatElement.CT_TransDrawCall : Laya.StatElement.CT_OpaqueDrawCall, this.elements.length);
        }
        mergeQueue() {
            this.sort();
            if (!this._isTransparent && this.batchModule.length > 0) {
                for (var i = 0, n = this.batchModule.length; i < n; i++) {
                    let list = this.batchModule.elements[i].opaqueList;
                    for (var j = 0, m = list.length; j < m; j++) {
                        let elements = list.elements;
                        this._elements.add(elements[j]);
                    }
                }
            }
        }
        renderQueueOnly(context) {
            context.drawRenderElementList(this._elements);
            Laya.LayaGL.statAgent.recordCTData(this._isTransparent ? Laya.StatElement.CT_TransDrawCall : Laya.StatElement.CT_OpaqueDrawCall, this.elements.length);
        }
        sort() {
            const count = this._elements.length;
            this._quickSort.sort(this._elements, this._isTransparent, 0, count - 1);
        }
        clear() {
            this._elements.elements.fill(null);
            this._elements.length = 0;
            this.batchModule.length = 0;
        }
        destroy() {
            this.clear();
            this._elements = null;
        }
    }

    class RenderPassUtil {
        static renderCmd(cmds, context) {
            if (cmds && cmds.length > 0)
                cmds.forEach(value => context.runCMDList(value._renderCMDs));
        }
        static recoverRenderContext3D(context, renderTarget) {
            context.setViewPort(this.contextViewPortCache);
            context.setScissor(this.contextScissorCache);
            context.setRenderTarget(renderTarget, Laya.RenderClearFlag.Nothing);
        }
    }
    RenderPassUtil.contextViewPortCache = new Laya.Viewport();
    RenderPassUtil.contextScissorCache = new Laya.Vector4();

    class WebBaseRenderNode {
        get shaderData() {
            return this._shaderData;
        }
        set shaderData(value) {
            if (this._shaderData != value) {
                let oldCommandMap = this._commonUniformMap.slice();
                if (this._shaderData) {
                    this.setCommonUniformMap([]);
                }
                this._shaderData = value;
                this.setCommonUniformMap(oldCommandMap);
            }
        }
        _renderUpdatePre(context3D) {
            const mask = this.perCameraUpdate
                ? context3D.cameraUpdateMask
                : context3D.sceneUpdateMask;
            if (this._updateMark == mask)
                return;
            this._renderUpdatePreFun.call(this._renderUpdatePreCall, context3D);
            this._updateMark = mask;
        }
        _calculateBoundingBox() {
            this._caculateBoundingBoxFun.call(this._caculateBoundingBoxCall);
        }
        get bounds() {
            if (this.boundsChange) {
                this._calculateBoundingBox();
                this.boundsChange = false;
            }
            return this._bounds;
        }
        set bounds(value) {
            this._bounds = value;
        }
        get additionShaderData() {
            return this._additionShaderData;
        }
        set additionShaderData(value) {
            if (this._additionShaderData && this._additionShaderData.size > 0) {
                if (!value)
                    for (var [key, date] of this._additionShaderData) {
                        date.getDefineData().removeChangeFlagInfo(this.defineDataChangeFlag);
                    }
                else {
                    for (var [key, date] of this._additionShaderData) {
                        if (!value.has(key)) {
                            date.getDefineData().removeChangeFlagInfo(this.defineDataChangeFlag);
                        }
                    }
                }
            }
            this._additionShaderData = value;
            if (value && value.size > 0) {
                this._additionShaderDataKeys = Array.from(this._additionShaderData.keys());
                for (var [key, shaderdate] of value) {
                    shaderdate.getDefineData().addChangeFlagInfo(this.defineDataChangeFlag);
                }
            }
            else {
                this._additionShaderDataKeys = [];
            }
        }
        constructor() {
            this.ismoved = new Laya.Vector2();
            this.defineDataChangeFlag = new Laya.Vector2();
            this.perCameraUpdate = false;
            this.renderelements = [];
            this._commonUniformMap = [];
            this._worldParams = new Laya.Vector4(1, 0, 0, 0);
            this.lightmapDirtyFlag = -1;
            this.lightmapScaleOffset = new Laya.Vector4(1, 1, 0, 0);
            this.set_caculateBoundingBox(this, this._ownerCalculateBoundingBox);
            this._additionShaderData = new Map();
        }
        setNodeCustomData(dataSlot, data) {
            switch (dataSlot) {
                case 0:
                    this._worldParams.y = data;
                    break;
                case 1:
                    this._worldParams.z = data;
                    break;
                case 2:
                    this._worldParams.w = data;
                    break;
            }
        }
        set_renderUpdatePreCall(call, fun) {
            this._renderUpdatePreCall = call;
            this._renderUpdatePreFun = fun;
        }
        set_caculateBoundingBox(call, fun) {
            this._caculateBoundingBoxCall = call;
            this._caculateBoundingBoxFun = fun;
        }
        _needRender(boundFrustum) {
            if (boundFrustum)
                return boundFrustum.intersects(this.bounds);
            else
                return true;
        }
        setRenderelements(value) {
            this.renderelements.length = 0;
            for (var i = 0; i < value.length; i++) {
                this.renderelements.push(value[i]);
                value[i].owner = this;
            }
        }
        setOneMaterial(index, mat) {
            if (!this.renderelements[index])
                return;
            this.renderelements[index].materialShaderData = mat.shaderData;
            this.renderelements[index].materialRenderQueue = mat.renderQueue;
            this.renderelements[index].subShader = mat.shader.getSubShaderAt(0);
            this.renderelements[index].materialId = mat._id;
        }
        setLightmapScaleOffset(value) {
            value && value.cloneTo(this.lightmapScaleOffset);
        }
        setCommonUniformMap(value) {
            var _a;
            this._commonUniformMap.length = 0;
            value.forEach(element => {
                this._commonUniformMap.push(element);
            });
            this._shaderData && ((_a = this._shaderData.getDefineData()) === null || _a === void 0 ? void 0 : _a.addChangeFlagInfo(this.defineDataChangeFlag));
        }
        shadowCullPass() {
            return this.castShadow && this.enable && (this.renderbitFlag == 0);
        }
        _ownerCalculateBoundingBox() {
            this.baseGeometryBounds._tranform(this.transform.worldMatrix, this._bounds);
        }
        _applyLightMapParams() {
            let shaderValues = this.shaderData;
            if (this.lightmap) {
                let lightMap = this.lightmap;
                shaderValues.setVector(Laya.RenderableSprite3D.LIGHTMAPSCALEOFFSET, this.lightmapScaleOffset);
                shaderValues._setInternalTexture(Laya.RenderableSprite3D.LIGHTMAP, lightMap.lightmapColor);
                shaderValues.addDefine(Laya.RenderableSprite3D.SAHDERDEFINE_LIGHTMAP);
                if (lightMap.lightmapDirection) {
                    shaderValues._setInternalTexture(Laya.RenderableSprite3D.LIGHTMAP_DIRECTION, lightMap.lightmapDirection);
                    shaderValues.addDefine(Laya.RenderableSprite3D.SHADERDEFINE_LIGHTMAP_DIRECTIONAL);
                }
                else {
                    shaderValues.removeDefine(Laya.RenderableSprite3D.SHADERDEFINE_LIGHTMAP_DIRECTIONAL);
                }
            }
            else {
                shaderValues.removeDefine(Laya.RenderableSprite3D.SAHDERDEFINE_LIGHTMAP);
                shaderValues.removeDefine(Laya.RenderableSprite3D.SHADERDEFINE_LIGHTMAP_DIRECTIONAL);
            }
        }
        _applyLightProb() {
            if (this.lightmapIndex >= 0 || !this.volumetricGI)
                return;
            if (this.volumetricGI.updateMark != this.lightProbUpdateMark) {
                this.lightProbUpdateMark = this.volumetricGI.updateMark;
                this.volumetricGI.applyRenderData();
            }
        }
        _applyReflection() {
            if (!this.probeReflection || this.reflectionMode == Laya.ReflectionProbeMode.off)
                return;
            if (this.probeReflection.needUpdate()) {
                this.probeReflection.applyRenderData();
            }
        }
        destroy() {
            this.renderelements.forEach(element => {
                element.destroy();
            });
            this.baseGeometryBounds = null;
            this.transform = null;
            this.lightmapScaleOffset = null;
            this.lightmap = null;
            this.probeReflection = null;
            this.volumetricGI = null;
            this.renderelements.length = 0;
            this.renderelements = null;
            this.shaderData && this.shaderData.destroy();
            this.shaderData = null;
            this._commonUniformMap.length = 0;
            this._commonUniformMap = null;
            this.additionShaderData.clear();
            this.additionShaderData = null;
            this._additionShaderDataKeys.length = 0;
            this._additionShaderDataKeys = null;
        }
    }

    class WebDirectLight {
        constructor() {
            this._shadowFourCascadeSplits = new Laya.Vector3();
            this._direction = new Laya.Vector3();
        }
        setShadowFourCascadeSplits(value) {
            value && value.cloneTo(this._shadowFourCascadeSplits);
        }
        setDirection(value) {
            value && value.cloneTo(this._direction);
        }
    }

    class WebLightmap {
        destroy() {
            this.lightmapColor = null;
            this.lightmapDirection = null;
        }
    }

    var baseRenderNode = null;
    function WebMeshRenderNode() {
        if (!baseRenderNode)
            baseRenderNode = class extends WebBaseRenderNode.BaseRenderNodeClass {
                constructor() {
                    super();
                    this._cacheMoved = new Laya.Vector2(-1, -1);
                    this.set_renderUpdatePreCall(this, this._renderUpdate);
                }
                _renderUpdate(context) {
                    if (context.sceneModuleData.lightmapDirtyFlag != this.lightmapDirtyFlag) {
                        this._applyLightMapParams();
                        this.lightmapDirtyFlag = context.sceneModuleData.lightmapDirtyFlag;
                    }
                    this._applyReflection();
                    this._applyLightProb();
                    if (this.ismoved.x > this._cacheMoved.x || (this.ismoved.x == this._cacheMoved.x && this.ismoved.y > this._cacheMoved.y)) {
                        let trans = this.transform;
                        this.shaderData.setMatrix4x4(Laya.Sprite3D.WORLDMATRIX, trans.worldMatrix);
                        this._worldParams.x = trans.getFrontFaceValue();
                        this.shaderData.setVector(Laya.Sprite3D.WORLDINVERTFRONT, this._worldParams);
                        this.ismoved.cloneTo(this._cacheMoved);
                    }
                }
            };
        return baseRenderNode;
    }

    class WebCameraNodeData {
        constructor() {
            this._projectViewMatrix = new Laya.Matrix4x4();
        }
        setProjectionViewMatrix(value) {
            value && value.cloneTo(this._projectViewMatrix);
        }
    }
    class WebSceneNodeData {
    }

    class WebPointLight {
    }

    class WebReflectionProbe {
        constructor() {
            this._id = ++WebReflectionProbe._idCounter;
            this._updateMaskFlag = -1;
            this._shCoefficients = [];
            this._probePosition = new Laya.Vector3();
            this._ambientColor = new Laya.Color();
            this.shaderData = Laya.LayaGL.renderDeviceFactory.createShaderData();
        }
        needUpdate() {
            return this.updateMark != this._updateMaskFlag;
        }
        destroy() {
            this.bound = null;
            delete this._shCoefficients;
            delete this._ambientSH;
            this.shaderData.destroy();
            this.shaderData = null;
        }
        setAmbientSH(value) {
            this._ambientSH = value;
        }
        setShCoefficients(value) {
            this._shCoefficients.length = 0;
            value.forEach(element => {
                var v4 = new Laya.Vector4();
                element.cloneTo(v4);
                this._shCoefficients.push(v4);
            });
        }
        setProbePosition(value) {
            value && value.cloneTo(this._probePosition);
        }
        setreflectionHDRParams(value) {
            value && value.cloneTo(this._reflectionHDRParams);
        }
        setAmbientColor(value) {
            value && value.cloneTo(this._ambientColor);
        }
        applyRenderData() {
            this._updateMaskFlag = this.updateMark;
            let data = this.shaderData;
            if (!this.boxProjection) {
                data.removeDefine(Laya.Sprite3DRenderDeclaration.SHADERDEFINE_SPECCUBE_BOX_PROJECTION);
            }
            else {
                data.addDefine(Laya.Sprite3DRenderDeclaration.SHADERDEFINE_SPECCUBE_BOX_PROJECTION);
                data.setVector3(Laya.ReflectionProbe.REFLECTIONCUBE_PROBEPOSITION, this._probePosition);
                data.setVector3(Laya.ReflectionProbe.REFLECTIONCUBE_PROBEBOXMAX, this.bound.getMax());
                data.setVector3(Laya.ReflectionProbe.REFLECTIONCUBE_PROBEBOXMIN, this.bound.getMin());
            }
            if (this.ambientMode == Laya.AmbientMode.SolidColor) {
                data.removeDefine(Laya.Sprite3DRenderDeclaration.SHADERDEFINE_GI_LEGACYIBL);
                data.removeDefine(Laya.ReflectionProbe.SHADERDEFINE_GI_IBL);
                data.setColor(Laya.ReflectionProbe.AMBIENTCOLOR, this._ambientColor);
            }
            else if (this.iblTex && this._ambientSH) {
                data.addDefine(Laya.ReflectionProbe.SHADERDEFINE_GI_IBL);
                data.removeDefine(Laya.Sprite3DRenderDeclaration.SHADERDEFINE_GI_LEGACYIBL);
                if (this.iblTex) {
                    data._setInternalTexture(Laya.ReflectionProbe.IBLTEX, this.iblTex);
                    data.setNumber(Laya.ReflectionProbe.IBLROUGHNESSLEVEL, this.iblTex.maxMipmapLevel);
                }
                this.iblTexRGBD ? data.addDefine(Laya.Sprite3DRenderDeclaration.SHADERDEFINE_IBL_RGBD) : data.removeDefine(Laya.Sprite3DRenderDeclaration.SHADERDEFINE_IBL_RGBD);
                this._ambientSH && data.setBuffer(Laya.ReflectionProbe.AMBIENTSH, this._ambientSH);
            }
            else {
                data.removeDefine(Laya.Sprite3DRenderDeclaration.SHADERDEFINE_GI_LEGACYIBL);
                data.removeDefine(Laya.ReflectionProbe.SHADERDEFINE_GI_IBL);
            }
            data.setNumber(Laya.ReflectionProbe.AMBIENTINTENSITY, this.ambientIntensity);
            data.setNumber(Laya.ReflectionProbe.REFLECTIONINTENSITY, this.reflectionIntensity);
            data.update(Laya.ReflectionProbe.BlockName);
        }
    }
    WebReflectionProbe._idCounter = 0;

    var CLSSK = null;
    function WebSkinRenderNode() {
        if (!CLSSK)
            CLSSK = class extends WebBaseRenderNode.BaseRenderNodeClass {
                constructor() {
                    super();
                    this._bones = [];
                    this.set_renderUpdatePreCall(this, this._renderUpdate);
                }
                setRootBoneTransfom(value) {
                    this._cacheRootBone = value.transform;
                }
                setOwnerTransform(value) {
                    this._owner = value.transform;
                }
                setCacheMesh(cacheMesh) {
                    this._cacheMesh = cacheMesh;
                    this._skinnedDataLoopMarks = new Uint32Array(cacheMesh._inverseBindPoses.length);
                }
                setBones(value) {
                    this._bones = value;
                }
                setSkinnedData(value) {
                    this._skinnedData = value;
                }
                computeSkinnedData() {
                    var bindPoses = this._cacheMesh._inverseBindPoses;
                    var pathMarks = this._cacheMesh._skinnedMatrixCaches;
                    for (var i = 0, n = this._cacheMesh.subMeshCount; i < n; i++) {
                        var subMeshBoneIndices = ((this._cacheMesh.getSubMesh(i)))._boneIndicesList;
                        var subData = this._skinnedData[i];
                        for (var j = 0, m = subMeshBoneIndices.length; j < m; j++) {
                            var boneIndices = subMeshBoneIndices[j];
                            this._computeSubSkinnedData(bindPoses, boneIndices, subData[j], pathMarks);
                        }
                    }
                }
                _computeSubSkinnedData(bindPoses, boneIndices, data, matrixCaches) {
                    for (let k = 0, q = boneIndices.length; k < q; k++) {
                        let index = boneIndices[k];
                        if (this._skinnedDataLoopMarks[index] === Laya.Stat.loopCount) {
                            let c = matrixCaches[index];
                            let preData = this._skinnedData[c.subMeshIndex][c.batchIndex];
                            let srcIndex = c.batchBoneIndex * 16;
                            let dstIndex = k * 16;
                            for (let d = 0; d < 16; d++)
                                data[dstIndex + d] = preData[srcIndex + d];
                        }
                        else {
                            let bone = this._bones[index];
                            if (bone)
                                Laya.Utils3D._mulMatrixArray(bone.transform.worldMatrix.elements, bindPoses[index].elements, 0, data, k * 16);
                            this._skinnedDataLoopMarks[index] = Laya.Stat.loopCount;
                        }
                    }
                }
                _renderUpdate(context3D) {
                    let mat = this._owner.worldMatrix;
                    let worldParams = this._worldParams;
                    worldParams.x = this._owner.getFrontFaceValue();
                    if (this._cacheRootBone) {
                        mat = Laya.Matrix4x4.DEFAULT;
                        worldParams.x = 1;
                    }
                    this._applyLightProb();
                    this._applyReflection();
                    this.shaderData.setMatrix4x4(Laya.Sprite3D.WORLDMATRIX, mat);
                    this.shaderData.setVector(Laya.Sprite3D.WORLDINVERTFRONT, worldParams);
                }
            };
        return CLSSK;
    }

    class WebSpotLight {
        setDirection(value) {
            value.cloneTo(this._direction);
        }
        getWorldMatrix(out) {
            var position = this.transform.position;
            var quaterian = this.transform.rotation;
            Laya.Matrix4x4.createAffineTransformation(position, quaterian, Laya.Vector3.ONE, out);
            return out;
        }
    }

    class WebVolumetricGI {
        constructor() {
            this._id = ++WebVolumetricGI._idCounter;
            this._probeCounts = new Laya.Vector3();
            this._probeStep = new Laya.Vector3();
            this._params = new Laya.Vector4();
            this._params = new Laya.Vector4();
            this.bound = new Laya.Bounds();
            this.shaderData = Laya.LayaGL.renderDeviceFactory.createShaderData();
        }
        setParams(value) {
            value.cloneTo(this._params);
        }
        setProbeCounts(value) {
            value.cloneTo(this._probeCounts);
        }
        setProbeStep(value) {
            value.cloneTo(this._probeStep);
        }
        applyRenderData() {
            let data = this.shaderData;
            data.addDefine(Laya.VolumetricGI.SHADERDEFINE_VOLUMETRICGI);
            data.setVector3(Laya.VolumetricGI.VOLUMETRICGI_PROBECOUNTS, this._probeCounts);
            data.setVector3(Laya.VolumetricGI.VOLUMETRICGI_PROBESTEPS, this._probeStep);
            data.setVector3(Laya.VolumetricGI.VOLUMETRICGI_PROBESTARTPOS, this.bound.getMin());
            data.setVector(Laya.VolumetricGI.VOLUMETRICGI_PROBEPARAMS, this._params);
            data._setInternalTexture(Laya.VolumetricGI.VOLUMETRICGI_IRRADIANCE, this.irradiance);
            data._setInternalTexture(Laya.VolumetricGI.VOLUMETRICGI_DISTANCE, this.distance);
            data.setNumber(Laya.ReflectionProbe.AMBIENTINTENSITY, this.intensity);
            data.update(Laya.VolumetricGI.BlockName);
        }
        destroy() {
            this.shaderData.destroy();
            this.shaderData = null;
            this.irradiance = null;
            this.distance = null;
            this.bound = null;
        }
    }
    WebVolumetricGI._idCounter = 0;

    var CLASSIMPLESKIN = null;
    function WebSimpleSkinRenderNode() {
        if (!CLASSIMPLESKIN)
            CLASSIMPLESKIN = class extends WebBaseRenderNode.BaseRenderNodeClass {
                constructor() {
                    super();
                    this.set_renderUpdatePreCall(this, this._renderUpdate);
                    this._simpleAnimatorParams = new Laya.Vector4();
                }
                setSimpleAnimatorParams(value) {
                    value.cloneTo(this._simpleAnimatorParams);
                    this.shaderData.setVector(Laya.SimpleSkinnedMeshSprite3D.SIMPLE_SIMPLEANIMATORPARAMS, this._simpleAnimatorParams);
                }
                _renderUpdate(context3D) {
                    let shaderData = this.shaderData;
                    let worldMat = this.transform.worldMatrix;
                    let worldParams = this._worldParams;
                    worldParams.x = this.transform.getFrontFaceValue();
                    shaderData.setMatrix4x4(Laya.Sprite3D.WORLDMATRIX, worldMat);
                    shaderData.setVector(Laya.Sprite3D.WORLDINVERTFRONT, worldParams);
                    this._applyLightProb();
                    this._applyReflection();
                    shaderData.setVector(Laya.SimpleSkinnedMeshSprite3D.SIMPLE_SIMPLEANIMATORPARAMS, this._simpleAnimatorParams);
                }
            };
        return CLASSIMPLESKIN;
    }

    class Web3DRenderModuleFactory {
        createSimpleSkinRenderNode() {
            return new (WebSimpleSkinRenderNode())();
        }
        createTransform(owner) {
            return new Laya.Transform3D(owner);
        }
        createBounds(min, max) {
            return new Laya.BoundsImpl(min, max);
        }
        createVolumetricGI() {
            return new WebVolumetricGI();
        }
        createReflectionProbe() {
            return new WebReflectionProbe();
        }
        createLightmapData() {
            return new WebLightmap();
        }
        createDirectLight() {
            return new WebDirectLight();
        }
        createSpotLight() {
            return new WebSpotLight();
        }
        createPointLight() {
            return new WebPointLight();
        }
        createCameraModuleData() {
            return new WebCameraNodeData();
        }
        createSceneModuleData() {
            return new WebSceneNodeData();
        }
        createBaseRenderNode() {
            let renderNode = new WebBaseRenderNode();
            return renderNode;
        }
        createMeshRenderNode() {
            return new (WebMeshRenderNode())();
        }
        createSkinRenderNode() {
            return new (WebSkinRenderNode())();
        }
    }
    Laya.Laya.addBeforeInitCallback(() => {
        if (!Laya.Laya3DRender.Render3DModuleDataFactory) {
            Laya.Laya3DRender.Render3DModuleDataFactory = new Web3DRenderModuleFactory();
        }
    });

    class WebForwardAddClusterRP {
        get camera() {
            return this._camera;
        }
        set camera(value) {
            this._camera = value;
            this._setCameraCullInfo(this.camera);
        }
        get clearColor() {
            return this._clearColor;
        }
        set clearColor(value) {
            this._clearColor = value;
        }
        _setCameraCullInfo(value) {
            this._cameraCullInfo.position = value._transform.position;
            this._cameraCullInfo.cullingMask = value.cullingMask;
            this._cameraCullInfo.staticMask = value.staticMask;
            this._cameraCullInfo.boundFrustum = value.boundFrustum;
            this._cameraCullInfo.useOcclusionCulling = value.useOcclusionCulling;
            this._cameraCullInfo.id = value.id;
        }
        _clearRenderList() {
            this._opaqueList.clear();
            this._transparent.clear();
        }
        setCameraCullInfo(sceneManager) {
            let agent = sceneManager.batchAgentList;
            for (var [key, value] of agent) {
                value.setCullCamera([this._cameraCullInfo]);
            }
        }
        constructor() {
            this._opaqueList = new RenderListQueue(false);
            this._transparent = new RenderListQueue(true);
            this._cameraCullInfo = new Laya.CameraCullInfo();
            this._zBufferParams = new Laya.Vector4();
            this._scissor = new Laya.Vector4();
            this._viewPort = new Laya.Viewport();
            this._defaultNormalDepthColor = new Laya.Color(0.5, 0.5, 1.0, 0.0);
            this._clearColor = new Laya.Color();
            this.blitOpaqueBuffer = new Laya.CommandBuffer();
            this.depthPipelineMode = "ShadowCaster";
            this.depthNormalPipelineMode = "DepthNormal";
        }
        setViewPort(value) {
            value.cloneTo(this._viewPort);
        }
        setScissor(value) {
            value.cloneTo(this._scissor);
        }
        setBeforeForwardCmds(value) {
            if (value && value.length > 0) {
                this._beforeForwardCmds = value;
                value.forEach(element => element._apply(false));
            }
        }
        setBeforeSkyboxCmds(value) {
            if (value && value.length > 0) {
                this._beforeSkyboxCmds = value;
                value.forEach(element => element._apply(false));
            }
        }
        setBeforeTransparentCmds(value) {
            if (value && value.length > 0) {
                this._beforeTransparentCmds = value;
                value.forEach(element => element._apply(false));
            }
        }
        render(context, renderManager) {
            context.cameraUpdateMask++;
            this._clearRenderList();
            var time = performance.now();
            let _list = renderManager.baseRenderList;
            RenderCullUtil.cullByCameraCullInfo(this._cameraCullInfo, _list.elements, _list.length, this._opaqueList, this._transparent, context);
            let agent = renderManager.batchAgentList;
            for (var [key, agentModule] of agent) {
                let agentrenderList = agentModule.appendRenderElement(Laya.BatchCullMode.Camera, 0, context);
                let opaqueList = agentrenderList.opaqueList;
                let translist = agentrenderList.transparentList;
                if (agentrenderList.opaqueCustomSort) {
                    this._opaqueList.addBatchAgent(agentrenderList);
                }
                else {
                    let element = opaqueList.elements;
                    for (var jj = 0; jj < opaqueList.length; jj++) {
                        this._opaqueList.addRenderElement(element[jj]);
                    }
                }
                let element = translist.elements;
                for (var jj = 0; jj < translist.length; jj++) {
                    this._transparent.addRenderElement(element[jj]);
                }
            }
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_CullMain, performance.now() - time);
            time = performance.now();
            this._opaqueList.mergeQueue();
            if ((this.depthTextureMode & Laya.DepthTextureMode.Depth) != 0)
                this._renderDepthPass(context);
            if ((this.depthTextureMode & Laya.DepthTextureMode.DepthNormals) != 0)
                this._renderDepthNormalPass(context);
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_DepthPass, performance.now() - time);
            time = performance.now();
            this._mainPass(context);
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_3DMainPass, performance.now() - time);
        }
        _renderDepthNormalPass(context) {
            context.pipelineMode = this.depthNormalPipelineMode;
            this.camera._shaderValues.setTexture(Laya.DepthPass.DEPTHNORMALSTEXTURE, Laya.Texture2D.blackTexture);
            const viewport = this._viewPort;
            Laya.Viewport.TEMP.set(viewport.x, viewport.y, viewport.width, viewport.height);
            Laya.Vector4.TEMP.setValue(viewport.x, viewport.y, viewport.width, viewport.height);
            context.setViewPort(Laya.Viewport.TEMP);
            context.setScissor(Laya.Vector4.TEMP);
            context.setClearData(Laya.RenderClearFlag.Color | Laya.RenderClearFlag.Depth, this._defaultNormalDepthColor, 1, 0);
            context.setRenderTarget(this.depthNormalTarget, Laya.RenderClearFlag.Color | Laya.RenderClearFlag.Depth);
            this._opaqueList.renderQueueOnly(context);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_DepthCastDrawCall, this._opaqueList.elements.length);
            Laya.Camera.depthPass._setupDepthModeShaderValue(Laya.DepthTextureMode.DepthNormals, this.camera);
        }
        _renderDepthPass(context) {
            context.pipelineMode = this.depthPipelineMode;
            const viewport = this._viewPort;
            const shadervalue = context.sceneData;
            shadervalue.addDefine(Laya.DepthPass.DEPTHPASS);
            shadervalue.setVector(Laya.DepthPass.DEFINE_SHADOW_BIAS, Laya.Vector4.ZERO);
            Laya.Viewport.TEMP.set(viewport.x, viewport.y, viewport.width, viewport.height);
            Laya.Vector4.TEMP.setValue(viewport.x, viewport.y, viewport.width, viewport.height);
            context.setViewPort(Laya.Viewport.TEMP);
            context.setScissor(Laya.Vector4.TEMP);
            context.setRenderTarget(this.depthTarget, Laya.RenderClearFlag.Depth);
            context.setClearData(Laya.RenderClearFlag.Depth, Laya.Color.BLACK, 1, 0);
            this._opaqueList.renderQueueOnly(context);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_DepthCastDrawCall, this._opaqueList.elements.length);
            const far = this.camera.farPlane;
            const near = this.camera.nearPlane;
            this._zBufferParams.setValue(1.0 - far / near, far / near, (near - far) / (near * far), 1 / near);
            context.cameraData.setVector(Laya.DepthPass.DEFINE_SHADOW_BIAS, Laya.DepthPass.SHADOW_BIAS);
            context.cameraData.setVector(Laya.DepthPass.DEPTHZBUFFERPARAMS, this._zBufferParams);
            Laya.Camera.depthPass._setupDepthModeShaderValue(Laya.DepthTextureMode.Depth, this.camera);
            shadervalue.removeDefine(Laya.DepthPass.DEPTHPASS);
        }
        _mainPass(context) {
            context.pipelineMode = this.pipelineMode;
            RenderPassUtil.renderCmd(this._beforeForwardCmds, context);
            this._recoverRenderContext3D(context, this.destTarget);
            context.setClearData(this.clearFlag, this.clearColor, 1, 0);
            var time = performance.now();
            this._opaqueList.renderQueueOnly(context);
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_3DMainPass_Opaque, performance.now() - time);
            RenderPassUtil.renderCmd(this._beforeSkyboxCmds, context);
            if (this.skyRenderNode) {
                const skyRenderElement = this.skyRenderNode.renderelements[0];
                if (skyRenderElement.subShader)
                    context.drawRenderElementOne(skyRenderElement);
            }
            if (this.enableOpaque)
                this._opaqueTexturePass(context);
            RenderPassUtil.renderCmd(this._beforeTransparentCmds, context);
            this._recoverRenderContext3D(context, this.destTarget);
            time = performance.now();
            this._transparent.renderQueue(context);
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_3DMainPass_Trans, performance.now() - time);
        }
        _opaqueTexturePass(context) {
            let commanbuffer = this.blitOpaqueBuffer;
            commanbuffer._apply(false);
            context.runCMDList(commanbuffer._renderCMDs);
        }
        _recoverRenderContext3D(context, renderTarget) {
            context.setViewPort(this._viewPort);
            context.setScissor(this._scissor);
            context.setRenderTarget(renderTarget, Laya.RenderClearFlag.Nothing);
        }
        destory() {
        }
    }

    class WebForwardAddRP {
        constructor() {
            this.finalize = new Laya.CommandBuffer();
        }
        setBeforeImageEffect(value) {
            if (value && value.length > 0) {
                this._beforeImageEffectCMDS = value;
                value.forEach(element => element._apply(false));
            }
        }
        runBeforeImageEffectCMD(context) {
            this._renderCmd(this._beforeImageEffectCMDS, context);
        }
        setAfterEventCmd(value) {
            if (value && value.length > 0) {
                this._afterAllRenderCMDS = value;
                value.forEach(element => element._apply(false));
            }
        }
        runAfterEventCMD(context) {
            this._renderCmd(this._afterAllRenderCMDS, context);
        }
        _renderCmd(cmds, context) {
            if (cmds && cmds.length > 0)
                cmds.forEach(value => context.runCMDList(value._renderCMDs));
        }
        destroy() {
        }
    }

    const viewport$1 = new Laya.Viewport(0, 0, 0, 0);
    const offsetScale = new Laya.Vector4();
    class WebRender3DProcess {
        constructor() {
            this._defaultDepthTex = Laya.RenderTexture.createFromPool(1, 1, Laya.RenderTargetFormat.DEPTH_32, Laya.RenderTargetFormat.None, false, 1);
            this._defaultShadowMap = Laya.ShadowUtils.getTemporaryShadowTexture(1, 1, Laya.ShadowMapFormat.bit16);
            let shadowMap = Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap("Shadow");
            shadowMap.setDefaultTextureData(Laya.ShadowCasterPass.SHADOW_MAP, this._defaultShadowMap);
            shadowMap.setDefaultTextureData(Laya.ShadowCasterPass.SHADOW_SPOTMAP, this._defaultShadowMap);
        }
        _renderCmd(cmds, context) {
            if (cmds && cmds.length > 0)
                cmds.forEach(value => context.runCMDList(value._renderCMDs));
        }
        _renderPostProcess(postprocessCMD, context) {
            context.runCMDList(postprocessCMD._renderCMDs);
        }
        _initRenderPass(camera, context) {
            const renderPass = this._renderPass.mainRenderpass;
            const renderRT = camera._getRenderTexture();
            let clearConst = 0;
            const clearFlag = camera.clearFlag;
            const hasStencil = renderRT.depthStencilFormat === Laya.RenderTargetFormat.DEPTHSTENCIL_24_8;
            const stencilFlag = hasStencil ? Laya.RenderClearFlag.Stencil : 0;
            switch (clearFlag) {
                case Laya.CameraClearFlags.DepthOnly:
                    clearConst = Laya.RenderClearFlag.Depth | stencilFlag;
                    break;
                case Laya.CameraClearFlags.Nothing:
                    clearConst = Laya.RenderClearFlag.Nothing;
                    break;
                case Laya.CameraClearFlags.ColorOnly:
                    clearConst = Laya.RenderClearFlag.Color;
                    break;
                case Laya.CameraClearFlags.Sky:
                case Laya.CameraClearFlags.SolidColor:
                default:
                    clearConst = Laya.RenderClearFlag.Color | Laya.RenderClearFlag.Depth | stencilFlag;
                    break;
            }
            const clearValue = renderRT._texture.gammaCorrection !== 1 ? camera.clearColor : camera._linearClearColor;
            renderPass.camera = camera;
            renderPass.destTarget = renderRT._renderTarget;
            renderPass.clearFlag = clearConst;
            renderPass.clearColor = clearValue;
            let needInternalRT = camera._needInternalRenderTexture();
            renderPass.setCameraCullInfo(this.render3DManager);
            if (needInternalRT) {
                viewport$1.set(0, 0, renderRT.width, renderRT.height);
            }
            else {
                camera.viewport.cloneTo(viewport$1);
            }
            renderPass.setViewPort(viewport$1);
            let scissor = Laya.Vector4.TEMP;
            scissor.setValue(viewport$1.x, viewport$1.y, viewport$1.width, viewport$1.height);
            renderPass.setScissor(scissor);
            renderPass.enableOpaque = Laya.Stat.enableOpaque;
            renderPass.enableTransparent = Laya.Stat.enableTransparent;
            renderPass.enableCMD = Laya.Stat.enableCameraCMD;
            renderPass.setBeforeSkyboxCmds(camera._cameraEventCommandBuffer[Laya.CameraEventFlags.BeforeSkyBox]);
            renderPass.setBeforeForwardCmds(camera._cameraEventCommandBuffer[Laya.CameraEventFlags.BeforeForwardOpaque]);
            renderPass.setBeforeTransparentCmds(camera._cameraEventCommandBuffer[Laya.CameraEventFlags.BeforeTransparent]);
            this._renderPass.setBeforeImageEffect(camera._cameraEventCommandBuffer[Laya.CameraEventFlags.BeforeImageEffect]);
            this._renderPass.setAfterEventCmd(camera._cameraEventCommandBuffer[Laya.CameraEventFlags.AfterEveryThing]);
            if (camera.clearFlag === Laya.CameraClearFlags.Sky)
                renderPass.skyRenderNode = camera.scene.skyRenderer._baseRenderNode;
            else
                renderPass.skyRenderNode = null;
            renderPass.pipelineMode = Laya.RenderContext3D._instance.configPipeLineMode;
            const enableShadow = (Laya.Scene3D._updateMark % camera.scene._ShadowMapupdateFrequency === 0) && Laya.Stat.enableShadow;
            this._renderPass.shadowCastPass = enableShadow;
            context.preDrawUniformMaps.add("Scene3D");
            context.preDrawUniformMaps.add("Global");
            if (enableShadow) {
                const mainDirectionLight = camera.scene._mainDirectionLight;
                const needDirectionShadow = mainDirectionLight && mainDirectionLight.shadowMode !== Laya.ShadowMode.None;
                this._renderPass.enableDirectLightShadow = needDirectionShadow;
                if (needDirectionShadow) {
                    this._renderPass.dirShadowRenderPass.setRPData(mainDirectionLight._dataModule, camera._renderDataModule, context, this.render3DManager);
                    this._renderPass.dirShadowRenderPass.setCameraCullInfo(this.render3DManager);
                }
                const mainSpotLight = camera.scene._mainSpotLight;
                const needSpotShadow = mainSpotLight && mainSpotLight.shadowMode !== Laya.ShadowMode.None;
                this._renderPass.enableSpotLightShadowPass = needSpotShadow;
                if (needSpotShadow) {
                    this._renderPass.spotShadowRenderPass.setRPData(mainSpotLight._dataModule, context, this.render3DManager);
                    this._renderPass.spotShadowRenderPass.setCameraCullInfo(this.render3DManager);
                }
                if (needDirectionShadow || needSpotShadow) {
                    context.preDrawUniformMaps.add("Shadow");
                }
            }
            else {
                context.preDrawUniformMaps.delete("Shadow");
            }
            if (Laya.Stat.enablePostprocess && camera.postProcess && camera.postProcess.enable && camera.postProcess.effects.length > 0) {
                this._renderPass.enablePostProcess = camera.postProcess.enable;
                this._renderPass.postProcess = camera.postProcess._context.command;
                camera.postProcess._render(camera);
                this._renderPass.postProcess._apply(false);
            }
            else
                this._renderPass.enablePostProcess = false;
            this._renderPass.finalize.clear();
            if (!this._renderPass.enablePostProcess && needInternalRT && camera._offScreenRenderTexture) {
                let dst = camera._offScreenRenderTexture;
                if (Laya.LayaGL.renderEngine._screenInvertY) {
                    offsetScale.setValue(camera.normalizedViewport.x, camera.normalizedViewport.y, renderRT.width / dst.width, renderRT.height / dst.height);
                }
                else
                    offsetScale.setValue(camera.normalizedViewport.x, 1.0 - camera.normalizedViewport.y, renderRT.width / dst.width, -renderRT.height / dst.height);
                this._renderPass.finalize.blitScreenQuad(renderRT, camera._offScreenRenderTexture, offsetScale);
            }
        }
        _renderDepth(camera) {
            let depthMode = camera.depthTextureMode;
            if (camera.postProcess && camera.postProcess.enable) {
                depthMode |= camera.postProcess.cameraDepthTextureMode;
            }
            if ((depthMode & Laya.DepthTextureMode.Depth) != 0) {
                Laya.Camera.depthPass.getTarget(camera, Laya.DepthTextureMode.Depth, camera.depthTextureFormat);
                this._renderPass.mainRenderpass.depthTarget = camera.depthTexture._renderTarget;
                Laya.Camera.depthPass._setupDepthModeShaderValue(Laya.DepthTextureMode.Depth, camera);
            }
            if ((depthMode & Laya.DepthTextureMode.DepthNormals) != 0) {
                Laya.Camera.depthPass.getTarget(camera, Laya.DepthTextureMode.DepthNormals, camera.depthTextureFormat);
                this._renderPass.mainRenderpass.depthNormalTarget = camera.depthNormalTexture._renderTarget;
                camera._shaderValues.setTexture(Laya.DepthPass.DEPTHNORMALSTEXTURE, camera.depthNormalTexture);
                Laya.Camera.depthPass._setupDepthModeShaderValue(Laya.DepthTextureMode.DepthNormals, camera);
            }
            this._renderPass.mainRenderpass.depthTextureMode = depthMode;
        }
        _renderForwardAddCameraPass(context, renderPass) {
            var time = Laya.Browser.now();
            context.cameraData.setTexture(Laya.DepthPass.DEPTHTEXTURE, this._defaultDepthTex);
            if (renderPass.shadowCastPass) {
                context.sceneData.setTexture(Laya.ShadowCasterPass.SHADOW_MAP, this._defaultShadowMap);
                context.sceneData.setTexture(Laya.ShadowCasterPass.SHADOW_SPOTMAP, this._defaultShadowMap);
                if (renderPass.enableDirectLightShadow) {
                    renderPass.dirShadowRenderPass.update(context);
                    renderPass.dirShadowRenderPass.render(context, this.render3DManager);
                }
                if (renderPass.enableSpotLightShadowPass) {
                    renderPass.spotShadowRenderPass.update(context);
                    renderPass.spotShadowRenderPass.render(context, this.render3DManager);
                }
            }
            if (renderPass.enableDirectLightShadow) {
                renderPass.dirShadowRenderPass.useRPResource(context);
            }
            else {
                renderPass.dirShadowRenderPass.unuseRPResource(context);
            }
            if (renderPass.enableSpotLightShadowPass) {
                renderPass.spotShadowRenderPass.useRPResource(context);
            }
            else {
                renderPass.spotShadowRenderPass.unuseRPResource(context);
            }
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_ShadowPass, Laya.Browser.now() - time);
            renderPass.mainRenderpass.render(context, this.render3DManager);
            renderPass.runBeforeImageEffectCMD(context);
            if (renderPass.enablePostProcess && renderPass.postProcess) {
                time = Laya.Browser.now();
                this._renderPostProcess(renderPass.postProcess, context);
                Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_Render_PostProcess, Laya.Browser.now() - time);
            }
            renderPass.runAfterEventCMD(context);
            renderPass.finalize._apply(false);
            context.runCMDList(renderPass.finalize._renderCMDs);
        }
        fowardRender(context, camera) {
            Laya.Camera.depthPass.cleanUp(camera);
            this._renderDepth(camera);
            this._initRenderPass(camera, context);
            this._renderForwardAddCameraPass(context, this._renderPass);
        }
        destroy() {
            this._defaultDepthTex.destroy();
            this._defaultDepthTex = null;
            this._renderPass.destroy();
        }
    }

    class WebSceneRenderManager {
        constructor() {
            this._list = new Laya.SingletonList();
            this.batchAgentList = new Map();
            this.baseRenderList = new Laya.SingletonList();
        }
        registerBatchModuleAgent(renderNodeType, agent) {
            if (!this.batchAgentList.has(renderNodeType)) {
                this.batchAgentList.set(renderNodeType, agent);
                for (let i = 0; i < this.baseRenderList.length; i++) {
                    if (this.baseRenderList.elements[i].renderNodeType == renderNodeType) {
                        agent.addRenderNode(this._list.elements[i]);
                        this._list.elements[i]._batchRender = agent;
                    }
                }
            }
        }
        updateProperty(object, property) {
            let agent = this.batchAgentList.get(object._baseRenderNode.renderNodeType);
            agent && agent.updateProperty(object, property);
        }
        get list() {
            return this._list;
        }
        set list(value) {
            this._list = value;
            if (value) {
                let elemnt = this._list.elements;
                this.baseRenderList.clear();
                for (let i = 0; i < this._list.length; i++) {
                    this.baseRenderList.add(elemnt[i]._baseRenderNode);
                }
            }
        }
        addRenderObject(object) {
            let agent = this.batchAgentList.get(object._baseRenderNode.renderNodeType);
            if (agent) {
                agent.addRenderNode(object);
                object._batchRender = agent;
            }
            else {
                this._list.add(object);
                this.baseRenderList.add(object._baseRenderNode);
            }
        }
        removeRenderObject(object) {
            let agent = this.batchAgentList.get(object._baseRenderNode.renderNodeType);
            if (agent) {
                agent.removeRenderNode(object);
                object._batchRender = null;
            }
            else {
                this._list.remove(object);
                this.baseRenderList.remove(object._baseRenderNode);
            }
        }
        removeMotionObject(object) {
        }
        updateMotionObjects() {
        }
        addMotionObject(object) {
        }
        destroy() {
            var _a;
            (_a = this._list) === null || _a === void 0 ? void 0 : _a.destroy();
            this.baseRenderList.destroy();
            this._list = null;
            this.baseRenderList = null;
            for (var [key, value] of this.batchAgentList) {
                value.release();
            }
        }
    }

    class WebBaseSpotRP {
        constructor() {
            this._shadowSpotMatrices = new Laya.Matrix4x4();
            this._shadowSpotMapSize = new Laya.Vector4();
            this._renderQueue = new RenderListQueue(false);
            this._shadowSpotData = new Laya.ShadowSpotData();
            this._lightWorldMatrix = new Laya.Matrix4x4();
            this._shadowBias = new Laya.Vector4();
        }
        _setLight(value) {
            this._light = value;
            this._shadowResolution = this._light.shadowResolution;
            this._lightWorldMatrix = this._light.getWorldMatrix(this._lightWorldMatrix);
            this._lightPos = this._light.transform.position;
            this._spotAngle = this._light.spotAngle;
            this._spotRange = this._light.spotRange;
            this._shadowStrength = this._light.shadowStrength;
            this._shadowMode = this._light.shadowMode;
        }
        _applyCasterPassCommandBuffer(context) {
            if (this._shadowCasterCommanBuffer && this._shadowCasterCommanBuffer.length > 0)
                this._shadowCasterCommanBuffer.forEach(value => value._apply());
        }
        _getSpotLightShadowData(shadowSpotData, resolution, shadowSpotMatrices, shadowMapSize) {
            var out = shadowSpotData.position = this._lightPos;
            shadowSpotData.resolution = resolution;
            shadowMapSize.setValue(1.0 / resolution, 1.0 / resolution, resolution, resolution);
            shadowSpotData.offsetX = 0;
            shadowSpotData.offsetY = 0;
            var spotWorldMatrix = this._lightWorldMatrix;
            var viewMatrix = shadowSpotData.viewMatrix;
            var projectMatrix = shadowSpotData.projectionMatrix;
            var viewProjectMatrix = shadowSpotData.viewProjectMatrix;
            var BoundFrustum = shadowSpotData.cameraCullInfo.boundFrustum;
            spotWorldMatrix.invert(viewMatrix);
            Laya.Matrix4x4.createPerspective(3.1416 * this._spotAngle / 180.0, 1, 0.1, this._spotRange, projectMatrix);
            Laya.Matrix4x4.multiply(projectMatrix, viewMatrix, viewProjectMatrix);
            BoundFrustum.matrix = viewProjectMatrix;
            viewProjectMatrix.cloneTo(shadowSpotMatrices);
            shadowSpotData.cameraCullInfo.position = out;
        }
        _getShadowBias(shadowResolution, out) {
            var frustumSize = Math.tan(this._spotAngle * 0.5 * Laya.MathUtils3D.Deg2Rad) * this._spotRange;
            var texelSize = frustumSize / shadowResolution;
            var depthBias = -this._light.shadowDepthBias * texelSize;
            var normalBias = -this._light.shadowNormalBias * texelSize;
            if (this._shadowMode == Laya.ShadowMode.SoftHigh) {
                const kernelRadius = 2.5;
                depthBias *= kernelRadius;
                normalBias *= kernelRadius;
            }
            out.setValue(depthBias, normalBias, 0.0, 0.0);
        }
        _setupShadowCasterShaderValues(shaderValues, shadowSliceData, shadowBias) {
            shaderValues.setVector(Laya.ShadowCasterPass.SHADOW_BIAS, shadowBias);
            var cameraSV = shadowSliceData.cameraShaderValue;
            cameraSV.setMatrix4x4(Laya.BaseCamera.VIEWMATRIX, shadowSliceData.viewMatrix);
            cameraSV.setMatrix4x4(Laya.BaseCamera.PROJECTMATRIX, shadowSliceData.projectionMatrix);
            cameraSV.setMatrix4x4(Laya.BaseCamera.VIEWPROJECTMATRIX, shadowSliceData.viewProjectMatrix);
            shaderValues.setMatrix4x4(Laya.BaseCamera.VIEWPROJECTMATRIX, shadowSliceData.viewProjectMatrix);
        }
        _applyRenderData(sceneData, cameraData) {
            var spotLight = this._light;
            switch (spotLight.shadowMode) {
                case Laya.ShadowMode.Hard:
                    sceneData.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SPOT_SOFT_SHADOW_HIGH);
                    sceneData.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SPOT_SOFT_SHADOW_LOW);
                    break;
                case Laya.ShadowMode.SoftLow:
                    sceneData.addDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SPOT_SOFT_SHADOW_LOW);
                    sceneData.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SPOT_SOFT_SHADOW_HIGH);
                    break;
                case Laya.ShadowMode.SoftHigh:
                    sceneData.addDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SPOT_SOFT_SHADOW_HIGH);
                    sceneData.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SPOT_SOFT_SHADOW_LOW);
                    break;
            }
            sceneData.setMatrix4x4(Laya.ShadowCasterPass.SHADOW_SPOTMATRICES, this._shadowSpotMatrices);
            sceneData.setVector(Laya.ShadowCasterPass.SHADOW_SPOTMAP_SIZE, this._shadowSpotMapSize);
        }
        setShadowCasterCommanBuffer(cmd) {
            this._shadowCasterCommanBuffer = cmd;
        }
        setCameraCullInfo(sceneManager) {
            const shadowSpotData = this._shadowSpotData;
            this._getSpotLightShadowData(shadowSpotData, this._shadowResolution, this._shadowSpotMatrices, this._shadowSpotMapSize);
            let agent = sceneManager.batchAgentList;
            for (var [key, value] of agent) {
                value.setSpotCullingDir([shadowSpotData.cameraCullInfo]);
            }
        }
        setRPData(spotLight, context) {
            this._setLight(spotLight);
            this._destShadowRT = Laya.Scene3D._shadowCasterPass.getSpotLightShadowPassData(spotLight);
            let v4 = context.sceneData.getVector(Laya.ShadowCasterPass.SHADOW_PARAMS);
            v4 = v4 ? v4 : new Laya.Vector4();
            v4.y = spotLight.shadowStrength;
            context.sceneData.setVector(Laya.ShadowCasterPass.SHADOW_PARAMS, v4);
        }
        update(context) {
            context.sceneData.addDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SPOT);
            context.sceneData.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW);
        }
        render(context, manager) {
            const originCameraData = context.cameraData;
            const shadowSpotData = this._shadowSpotData;
            const shaderData = context.sceneData;
            context.pipelineMode = 'ShadowCaster';
            context.setRenderTarget(this._destShadowRT._renderTarget, Laya.RenderClearFlag.Depth);
            this._getShadowBias(shadowSpotData.resolution, this._shadowBias);
            this._setupShadowCasterShaderValues(shaderData, shadowSpotData, this._shadowBias);
            let list = manager.baseRenderList;
            var time = Laya.Browser.now();
            RenderCullUtil.cullSpotShadow(shadowSpotData.cameraCullInfo, list.elements, list.length, this._renderQueue, context);
            let agent = manager.batchAgentList;
            for (var [key, agentModule] of agent) {
                let agentrenderList = agentModule.appendRenderElement(Laya.BatchCullMode.Spot, 0, context).opaqueList;
                let element = agentrenderList.elements;
                for (var jj = 0; jj < agentrenderList.length; jj++) {
                    this._renderQueue.addRenderElement(element[jj]);
                }
            }
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_CullShadow, Laya.Browser.now() - time);
            let cameraDepthTex = context.cameraData.getTexture(Laya.DepthPass.DEPTHTEXTURE);
            shadowSpotData.cameraShaderValue.setTexture(Laya.DepthPass.DEPTHTEXTURE, cameraDepthTex);
            context.cameraData = shadowSpotData.cameraShaderValue;
            context.cameraUpdateMask++;
            Laya.Viewport.TEMP.set(shadowSpotData.offsetX, shadowSpotData.offsetY, shadowSpotData.resolution, shadowSpotData.resolution);
            Laya.Vector4.TEMP.setValue(shadowSpotData.offsetX, shadowSpotData.offsetY, shadowSpotData.resolution, shadowSpotData.resolution);
            context.setViewPort(Laya.Viewport.TEMP);
            context.setScissor(Laya.Vector4.TEMP);
            context.setClearData(Laya.RenderClearFlag.Depth, Laya.Color.BLACK, 1, 0);
            this._renderQueue.renderQueue(context);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_ShadowDrawCall, this._renderQueue.elements.length);
            this._applyCasterPassCommandBuffer(context);
            this._applyRenderData(context.sceneData, context.cameraData);
            context.cameraData = originCameraData;
            context.cameraUpdateMask++;
        }
        useRPResource(context) {
            context.sceneData.addDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SPOT);
            context.sceneData.setTexture(Laya.ShadowCasterPass.SHADOW_SPOTMAP, this._destShadowRT);
        }
        unuseRPResource(context) {
            context.sceneData.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SPOT);
        }
        destory() {
        }
    }

    class WebDirCascadeShadowRP {
        constructor() {
            this._cascadesSplitDistance = new Array(WebDirCascadeShadowRP._maxCascades + 1);
            this._shadowMatrices = new Float32Array(16 * (WebDirCascadeShadowRP._maxCascades));
            this._splitBoundSpheres = new Float32Array(WebDirCascadeShadowRP._maxCascades * 4);
            this._shadowSliceDatas = [new Laya.ShadowSliceData(), new Laya.ShadowSliceData(), new Laya.ShadowSliceData(), new Laya.ShadowSliceData()];
            this._shadowMapSize = new Laya.Vector4();
            this._shadowBias = new Laya.Vector4();
            this._cascadeCount = 0;
            this._shadowMapWidth = 0;
            this._shadowMapHeight = 0;
            this._shadowTileResolution = 0;
            this._shadowCullInfo = [new Laya.ShadowCullInfo(), new Laya.ShadowCullInfo(), new Laya.ShadowCullInfo(), new Laya.ShadowCullInfo()];
            this._lightup = new Laya.Vector3();
            this._lightSide = new Laya.Vector3();
            this._lightForward = new Laya.Vector3();
            this._cascadesSplitDistance = new Array(WebDirCascadeShadowRP._maxCascades + 1);
            this._frustumPlanes = new Array(new Laya.Plane(new Laya.Vector3(), 0), new Laya.Plane(new Laya.Vector3(), 0), new Laya.Plane(new Laya.Vector3(), 0), new Laya.Plane(new Laya.Vector3(), 0), new Laya.Plane(new Laya.Vector3(), 0), new Laya.Plane(new Laya.Vector3(), 0));
            this._renderQueue = new RenderListQueue(false);
        }
        _setLight(value) {
            this._light = value;
            var lightWorld = Laya.Matrix4x4.TEMP;
            var lightWorldE = lightWorld.elements;
            var lightUp = this._lightup;
            var lightSide = this._lightSide;
            var lightForward = this._lightForward;
            Laya.Matrix4x4.createFromQuaternion(this._light.transform.rotation, lightWorld);
            lightSide.setValue(lightWorldE[0], lightWorldE[1], lightWorldE[2]);
            lightUp.setValue(lightWorldE[4], lightWorldE[5], lightWorldE[6]);
            lightForward.setValue(-lightWorldE[8], -lightWorldE[9], -lightWorldE[10]);
            var atlasResolution = this._light.shadowResolution;
            var cascadesMode = this._shadowCastMode = this._light.shadowCascadesMode;
            if (cascadesMode == Laya.ShadowCascadesMode.NoCascades) {
                this._cascadeCount = 1;
                this._shadowTileResolution = atlasResolution;
                this._shadowMapWidth = atlasResolution;
                this._shadowMapHeight = atlasResolution;
            }
            else {
                this._cascadeCount = cascadesMode == Laya.ShadowCascadesMode.TwoCascades ? 2 : 4;
                let shadowTileResolution = Laya.ShadowUtils.getMaxTileResolutionInAtlas(atlasResolution, atlasResolution, this._cascadeCount);
                this._shadowTileResolution = shadowTileResolution;
                this._shadowMapWidth = shadowTileResolution * 2;
                this._shadowMapHeight = cascadesMode == Laya.ShadowCascadesMode.TwoCascades ? shadowTileResolution : shadowTileResolution * 2;
            }
        }
        _getShadowBias(shadowProjectionMatrix, shadowResolution, out) {
            var frustumSize;
            frustumSize = 2.0 / shadowProjectionMatrix.elements[0];
            var texelSize = frustumSize / shadowResolution;
            var depthBias = -this._light.shadowDepthBias * texelSize;
            var normalBias = -this._light.shadowNormalBias * texelSize;
            if (this._light.shadowMode == Laya.ShadowMode.SoftHigh) {
                const kernelRadius = 2.5;
                depthBias *= kernelRadius;
                normalBias *= kernelRadius;
            }
            out.setValue(depthBias, normalBias, 0.0, 0.0);
        }
        _setupShadowCasterShaderValues(shaderValues, shadowSliceData, LightParam, shadowBias) {
            shaderValues.setVector(Laya.ShadowCasterPass.SHADOW_BIAS, shadowBias);
            shaderValues.setVector3(Laya.ShadowCasterPass.SHADOW_LIGHT_DIRECTION, LightParam);
            var cameraSV = shadowSliceData.cameraShaderValue;
            cameraSV.setMatrix4x4(Laya.BaseCamera.VIEWMATRIX, shadowSliceData.viewMatrix);
            cameraSV.setMatrix4x4(Laya.BaseCamera.PROJECTMATRIX, shadowSliceData.projectionMatrix);
            cameraSV.setMatrix4x4(Laya.BaseCamera.VIEWPROJECTMATRIX, shadowSliceData.viewProjectMatrix);
            shaderValues.setMatrix4x4(Laya.BaseCamera.VIEWPROJECTMATRIX, shadowSliceData.viewProjectMatrix);
        }
        _applyRenderData(scene, camera) {
            var light = this._light;
            if (light.shadowCascadesMode !== Laya.ShadowCascadesMode.NoCascades)
                scene.addDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_CASCADE);
            else
                scene.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_CASCADE);
            switch (light.shadowMode) {
                case Laya.ShadowMode.Hard:
                    scene.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SOFT_SHADOW_LOW);
                    scene.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SOFT_SHADOW_HIGH);
                    break;
                case Laya.ShadowMode.SoftLow:
                    scene.addDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SOFT_SHADOW_LOW);
                    scene.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SOFT_SHADOW_HIGH);
                    break;
                case Laya.ShadowMode.SoftHigh:
                    scene.addDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SOFT_SHADOW_HIGH);
                    scene.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SOFT_SHADOW_LOW);
                    break;
            }
            scene.setBuffer(Laya.ShadowCasterPass.SHADOW_MATRICES, this._shadowMatrices);
            scene.setVector(Laya.ShadowCasterPass.SHADOW_MAP_SIZE, this._shadowMapSize);
            scene.setBuffer(Laya.ShadowCasterPass.SHADOW_SPLIT_SPHERES, this._splitBoundSpheres);
        }
        _applyCasterPassCommandBuffer(context) {
            if (!this._shadowCasterCommanBuffer || this._shadowCasterCommanBuffer.length == 0)
                return;
            this._shadowCasterCommanBuffer.forEach(function (value) {
                value._apply();
            });
        }
        setShadowCasterCommanBuffer(cmd) {
            this._shadowCasterCommanBuffer = cmd;
        }
        _caculateDirCullInfo() {
            var splitDistance = this._cascadesSplitDistance;
            var frustumPlanes = this._frustumPlanes;
            var cameraNear = this._camera.nearplane;
            var shadowFar = Math.min(this._camera.farplane, this._light.shadowDistance);
            var shadowMatrices = this._shadowMatrices;
            var boundSpheres = this._splitBoundSpheres;
            Laya.ShadowUtils.getCascadesSplitDistance(this._light.shadowTwoCascadeSplits, this._light._shadowFourCascadeSplits, cameraNear, shadowFar, this._camera.fieldOfView * Laya.MathUtils3D.Deg2Rad, this._camera.aspectRatio, this._shadowCastMode, splitDistance);
            Laya.ShadowUtils.getCameraFrustumPlanes(this._camera._projectViewMatrix, frustumPlanes);
            var forward = Laya.Vector3.TEMP;
            this._camera.transform.getForward(forward);
            Laya.Vector3.normalize(forward, forward);
            for (var i = 0; i < this._cascadeCount; i++) {
                var sliceData = this._shadowSliceDatas[i];
                sliceData.sphereCenterZ = Laya.ShadowUtils.getBoundSphereByFrustum(splitDistance[i], splitDistance[i + 1], this._camera.fieldOfView * Laya.MathUtils3D.Deg2Rad, this._camera.aspectRatio, this._camera.transform.position, forward, sliceData.splitBoundSphere);
                Laya.ShadowUtils.getDirectionLightShadowCullPlanes(frustumPlanes, i, splitDistance, cameraNear, this._lightForward, sliceData);
                Laya.ShadowUtils.getDirectionalLightMatrices(this._lightup, this._lightSide, this._lightForward, i, this._light.shadowNearPlane, this._shadowTileResolution, sliceData, shadowMatrices);
                if (this._cascadeCount > 1)
                    Laya.ShadowUtils.applySliceTransform(sliceData, this._shadowMapWidth, this._shadowMapHeight, i, shadowMatrices);
            }
            Laya.ShadowUtils.prepareShadowReceiverShaderValues(this._shadowMapWidth, this._shadowMapHeight, this._shadowSliceDatas, this._cascadeCount, this._shadowMapSize, shadowMatrices, boundSpheres);
            for (var i = 0, n = this._cascadeCount; i < n; i++) {
                var shadowCullInfo = this._shadowCullInfo[i];
                var sliceData = this._shadowSliceDatas[i];
                shadowCullInfo.cameraPosition = this._camera.transform.position;
                shadowCullInfo.position = sliceData.position;
                shadowCullInfo.cullPlanes = sliceData.cullPlanes;
                shadowCullInfo.cullPlaneCount = sliceData.cullPlaneCount;
                shadowCullInfo.cullSphere = sliceData.splitBoundSphere;
                shadowCullInfo.direction = this._lightForward;
            }
        }
        setCameraCullInfo(sceneManager) {
            let cullInfos = this._shadowCullInfo.slice(0, this._cascadeCount);
            let agent = sceneManager.batchAgentList;
            for (var [key, value] of agent) {
                value.setDirLightCullInfo(cullInfos);
            }
        }
        setRPData(dirLight, camera, context) {
            this._setLight(dirLight);
            this._camera = camera;
            this._destShadowRT = Laya.Scene3D._shadowCasterPass.getDirectLightShadowMap(dirLight);
            let v4 = context.sceneData.getVector(Laya.ShadowCasterPass.SHADOW_PARAMS);
            v4 = v4 ? v4 : new Laya.Vector4();
            v4.x = dirLight.shadowStrength;
            context.sceneData.setVector(Laya.ShadowCasterPass.SHADOW_PARAMS, v4);
            context.sceneData.setTexture(Laya.ShadowCasterPass.SHADOW_MAP, this._defaultShadowMap);
            this._caculateDirCullInfo();
        }
        update(context) {
            context.sceneData.addDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW);
            context.sceneData.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW_SPOT);
        }
        render(context, manager) {
            let shaderValues = context.sceneData;
            context.pipelineMode = "ShadowCaster";
            var shadowMap = this._destShadowRT;
            context.setRenderTarget(shadowMap._renderTarget, Laya.RenderClearFlag.Depth);
            context.setClearData(Laya.RenderClearFlag.Depth, Laya.Color.BLACK, 1, 0);
            let originCameraData = context.cameraData;
            let originInvertY = context.invertY;
            for (var i = 0, n = this._cascadeCount; i < n; i++) {
                var sliceData = this._shadowSliceDatas[i];
                this._getShadowBias(sliceData.projectionMatrix, sliceData.resolution, this._shadowBias);
                this._setupShadowCasterShaderValues(shaderValues, sliceData, this._lightForward, this._shadowBias);
                var shadowCullInfo = this._shadowCullInfo[i];
                let list = manager.baseRenderList;
                var time = Laya.Browser.now();
                RenderCullUtil.cullDirectLightShadow(shadowCullInfo, list.elements, list.length, this._renderQueue, context);
                let agent = manager.batchAgentList;
                for (var [key, agentModule] of agent) {
                    let agentrenderList = agentModule.appendRenderElement(Laya.BatchCullMode.DirectLight, i, context).opaqueList;
                    let element = agentrenderList.elements;
                    for (var jj = 0; jj < agentrenderList.length; jj++) {
                        this._renderQueue.addRenderElement(element[jj]);
                    }
                }
                Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_CullShadow, performance.now() - time);
                context.cameraData = sliceData.cameraShaderValue;
                context.invertY = false;
                context.cameraUpdateMask++;
                var resolution = sliceData.resolution;
                var offsetX = sliceData.offsetX;
                var offsetY = sliceData.offsetY;
                Laya.Viewport.TEMP.set(offsetX, offsetY, resolution, resolution);
                Laya.Vector4.TEMP.setValue(offsetX + 1, offsetY + 1, resolution - 2, resolution - 2);
                context.setViewPort(Laya.Viewport.TEMP);
                context.setScissor(Laya.Vector4.TEMP);
                if (this._renderQueue.elements.length > 0) {
                    this._renderQueue.renderQueue(context);
                }
                else {
                    context.clearRenderTarget();
                }
                Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_ShadowDrawCall, this._renderQueue.elements.length);
                this._applyCasterPassCommandBuffer(context);
            }
            this._applyRenderData(context.sceneData, context.cameraData);
            context.cameraData = originCameraData;
            context.invertY = originInvertY;
            context.cameraUpdateMask++;
        }
        useRPResource(context) {
            context.sceneData.addDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW);
            context.sceneData.setTexture(Laya.ShadowCasterPass.SHADOW_MAP, this._destShadowRT);
        }
        unuseRPResource(context) {
            context.sceneData.removeDefine(Laya.Scene3DShaderDeclaration.SHADERDEFINE_SHADOW);
        }
        destory() {
        }
    }
    WebDirCascadeShadowRP._maxCascades = 4;

    class WebGLRenderElement3D {
        get subShader() {
            return this._subShader;
        }
        set subShader(value) {
            if (this._subShader != value) {
                this._subShader = value;
                this.modifyedMaterialShaderData();
            }
        }
        get materialShaderData() {
            return this._materialShaderData;
        }
        set materialShaderData(value) {
            if (this._materialShaderData != value) {
                this._materialShaderData = value;
                this._matChangeFlag.setValue(Laya.Stat.loopCount, Laya.WebGLEngine.instance._framePassCount);
                this.modifyedMaterialShaderData();
            }
        }
        modifyedMaterialShaderData() {
            this.subShaderChange = true;
            if (this.subShader && this.materialShaderData) {
                this._matChangeFlagMap.setValue(Laya.Stat.loopCount, Laya.WebGLEngine.instance._framePassCount);
                let changeFlag = this._matChangeFlagMap;
                this._materialShaderData._defineDatas.addChangeFlagInfo(changeFlag);
            }
        }
        get renderShaderData() {
            return this._renderShaderData;
        }
        set renderShaderData(value) {
            if (this._renderShaderData != value) {
                this._renderShaderData = value;
                this._renderNodeChangeFlag.setValue(Laya.Stat.loopCount, Laya.WebGLEngine.instance._framePassCount);
            }
        }
        constructor() {
            this.subShaderChange = false;
            this._matChangeFlagMap = new Laya.Vector2(-1, -1);
            this._passRenderInfo = new Map();
            this._materialRenderDataChange = true;
            this._spriteRenderDataChange = false;
            this._matChangeFlag = new Laya.Vector2();
            this._renderNodeChangeFlag = new Laya.Vector2();
        }
        _preUpdatePre(context) {
            if (!this._passRenderInfo.has(context._curRenderGlobalKey)) {
                this._curDrawCacheInfo = new Laya.OneDrawPassCacheInfo();
                this._passRenderInfo.set(context._curRenderGlobalKey, this._curDrawCacheInfo);
            }
            else {
                this._curDrawCacheInfo = this._passRenderInfo.get(context._curRenderGlobalKey);
            }
            this._updateMatChangeFlag();
            let passDefineChangeFlag = this._curDrawCacheInfo.passDefineCacheFlag;
            let compileShader = this._materialRenderDataChange || this._spriteRenderDataChange || !this._matDefChangeFlag;
            compileShader = compileShader || Laya.compareCahceFlag(this._matDefChangeFlag, passDefineChangeFlag);
            compileShader = compileShader || (this.owner ? Laya.compareCahceFlag(this.owner.defineDataChangeFlag, passDefineChangeFlag) : this.subShaderChange);
            compileShader = compileShader || Laya.compareCahceFlag(context._curDefineChangeFlag, passDefineChangeFlag);
            if (compileShader) {
                passDefineChangeFlag.setValue(Laya.Stat.loopCount, Laya.WebGLEngine.instance._framePassCount);
                this._compileShader(context);
            }
            if (this._materialRenderDataChange) {
                this._handleMaterialChange();
            }
            this._invertFront = this._getInvertFront();
            if (this.materialShaderData) {
                if (Laya.Config.matUseUBO) {
                    this.materialShaderData.uploadCache();
                    if (this.materialUBO) {
                        if (this.materialUBO.destroyed) {
                            this._handleMaterialChange();
                        }
                        this.materialUBO.upload();
                    }
                }
                if (this.materialShaderData.renderStateChanged) {
                    this.materialShaderData.updateRenderState();
                    let passes = this._curDrawCacheInfo.shaderInss;
                    for (let pass of passes) {
                        pass.updateRenderState(this.materialShaderData.renderState);
                    }
                }
            }
        }
        _getInvertFront() {
            var _a;
            let transform = (_a = this.owner) === null || _a === void 0 ? void 0 : _a.transform;
            return transform ? transform._isFrontFaceInvert : false;
        }
        _updateMatChangeFlag() {
            this._materialRenderDataChange = Laya.compareCahceFlag(this._matChangeFlag, this._curDrawCacheInfo.matCacheFlag);
            if (this._renderShaderData && Laya.compareCahceFlag(this._renderNodeChangeFlag, this._curDrawCacheInfo.nodeCacheFlag)) {
                this._curDrawCacheInfo.nodeCacheFlag.setValue(Laya.Stat.loopCount, Laya.WebGLEngine.instance._framePassCount);
                this._spriteRenderDataChange = true;
            }
            else {
                this._spriteRenderDataChange = false;
            }
        }
        _handleMaterialChange() {
            this._curDrawCacheInfo.matCacheFlag.setValue(Laya.Stat.loopCount, Laya.WebGLEngine.instance._framePassCount);
            this._matDefChangeFlag = this._matChangeFlagMap;
            if (this._materialShaderData && Laya.Config.matUseUBO) {
                let subShader = this._subShader;
                let materialData = this._materialShaderData;
                this.materialUBO = materialData.createSubUniformBuffer("Material", subShader._owner.name, subShader._uniformMap);
            }
            let passes = this._curDrawCacheInfo.shaderInss;
            for (let pass of passes) {
                pass.updateRenderState(this.materialShaderData.renderState);
            }
        }
        _render(context) {
            let forceInvertFace = context.invertY;
            let updateMark = context.cameraUpdateMask;
            let sceneShaderData = context.sceneData;
            let cameraShaderData = context.cameraData;
            if (this.isRender) {
                let passes = this._curDrawCacheInfo.shaderInss;
                for (let j = 0, m = passes.length; j < m; j++) {
                    const shaderIns = passes[j];
                    if (!shaderIns.complete)
                        continue;
                    let switchShader = shaderIns.bind();
                    let switchUpdateMark = (updateMark !== shaderIns._uploadMark);
                    let uploadScene = (shaderIns._uploadScene !== sceneShaderData) || switchUpdateMark;
                    if (uploadScene || switchShader) {
                        if (sceneShaderData) {
                            shaderIns.uploadUniforms(shaderIns._sceneUniformParamsMap, sceneShaderData, uploadScene);
                        }
                        shaderIns._uploadScene = sceneShaderData;
                    }
                    if (this._renderShaderData) {
                        let uploadSprite3D = (shaderIns._uploadRender !== this._renderShaderData) || switchUpdateMark;
                        if (uploadSprite3D || switchShader) {
                            shaderIns.uploadUniforms(shaderIns._spriteUniformParamsMap, this._renderShaderData, uploadSprite3D);
                            shaderIns._uploadRender = this._renderShaderData;
                        }
                    }
                    if (this.owner) {
                        let additionShaderData = this.owner.additionShaderData;
                        for (let [key, encoder] of shaderIns._additionUniformParamsMaps) {
                            let additionData = additionShaderData.get(key);
                            if (additionData) {
                                let needUpload = shaderIns._additionShaderData.get(key) !== additionData || switchUpdateMark;
                                if (needUpload || switchShader) {
                                    shaderIns.uploadUniforms(encoder, additionData, needUpload);
                                    shaderIns._additionShaderData.set(key, additionData);
                                }
                            }
                        }
                    }
                    let uploadCamera = shaderIns._uploadCameraShaderValue !== cameraShaderData || switchUpdateMark;
                    if (uploadCamera || switchShader) {
                        cameraShaderData && shaderIns.uploadUniforms(shaderIns._cameraUniformParamsMap, cameraShaderData, uploadCamera);
                        shaderIns._uploadCameraShaderValue = cameraShaderData;
                    }
                    let uploadMaterial = (shaderIns._uploadMaterial !== this._materialShaderData) || switchUpdateMark;
                    if (uploadMaterial || switchShader) {
                        shaderIns.uploadUniforms(shaderIns._materialUniformParamsMap, this._materialShaderData, uploadMaterial);
                        shaderIns._uploadMaterial = this._materialShaderData;
                    }
                    shaderIns.uploadRenderState(this._materialShaderData.renderState, forceInvertFace, this._invertFront);
                    this.drawGeometry(shaderIns);
                }
            }
        }
        _getShaderInstanceDefines(context) {
            let comDef = WebGLRenderElement3D._compileDefine;
            const globalShaderDefines = context._getContextShaderDefines();
            globalShaderDefines.cloneTo(comDef);
            if (this._renderShaderData) {
                comDef.addDefineDatas(this._renderShaderData.getDefineData());
            }
            if (this._materialShaderData) {
                comDef.addDefineDatas(this._materialShaderData._defineDatas);
            }
            if (this.owner) {
                let additionShaderData = this.owner.additionShaderData;
                if (additionShaderData.size > 0) {
                    for (let [key, value] of additionShaderData.entries()) {
                        comDef.addDefineDatas(value.getDefineData());
                    }
                }
            }
            return comDef;
        }
        _compileShader(context) {
            this.subShaderChange = false;
            var passes = this._subShader._passes;
            let renderCount = 0;
            for (var j = 0, m = passes.length; j < m; j++) {
                let pass = passes[j];
                let passdata = pass.moduleData;
                if (passdata.pipelineMode !== context.pipelineMode)
                    continue;
                if (this._renderShaderData) {
                    passdata.nodeCommonMap = this.owner._commonUniformMap;
                }
                else {
                    passdata.nodeCommonMap = null;
                }
                passdata.additionShaderData = null;
                if (this.owner) {
                    passdata.additionShaderData = this.owner._additionShaderDataKeys;
                }
                let comDef = this._getShaderInstanceDefines(context);
                var shaderIns = pass.withCompile(comDef);
                this._curDrawCacheInfo.shaderInss[renderCount] = shaderIns;
                renderCount++;
                if (this.materialShaderData) {
                    shaderIns.updateRenderState(this.materialShaderData.renderState);
                }
            }
            this._curDrawCacheInfo.shaderInss.length = renderCount;
        }
        drawGeometry(shaderIns) {
            Laya.WebGLEngine.instance.getDrawContext().drawGeometryElement(this.geometry);
        }
        destroy() {
            this.geometry = null;
            this.materialShaderData = null;
            this.renderShaderData = null;
            this.transform = null;
            this.isRender = null;
            this._passRenderInfo = null;
            this.materialUBO = null;
        }
    }
    WebGLRenderElement3D._compileDefine = new Laya.WebDefineDatas();

    class WebGLInstanceRenderElement3D extends WebGLRenderElement3D {
        static getInstanceBufferState(geometry, renderType, spriteDefine) {
            let stateinfo = WebGLInstanceRenderElement3D._instanceBufferStateMap.get(geometry._id);
            if (!stateinfo) {
                stateinfo = { state: new Laya.WebGLBufferState() };
                let oriBufferState = geometry.bufferState;
                let vertexArray = oriBufferState._vertexBuffers.slice();
                let worldMatVertex = new Laya.WebGLVertexBuffer(Laya.BufferTargetType.ARRAY_BUFFER, Laya.BufferUsage.Dynamic);
                worldMatVertex.setDataLength(WebGLInstanceRenderElement3D.MaxInstanceCount * 20 * 4);
                worldMatVertex.vertexDeclaration = Laya.VertexMesh.instanceWorldMatrixDeclaration;
                worldMatVertex.instanceBuffer = true;
                vertexArray.push(worldMatVertex);
                stateinfo.worldInstanceVB = worldMatVertex;
                switch (renderType) {
                    case Laya.BaseRenderType.MeshRender:
                        if (spriteDefine.has(Laya.MeshSprite3DShaderDeclaration.SHADERDEFINE_UV1)) {
                            let instanceLightMapVertexBuffer = new Laya.WebGLVertexBuffer(Laya.BufferTargetType.ARRAY_BUFFER, Laya.BufferUsage.Dynamic);
                            instanceLightMapVertexBuffer.setDataLength(WebGLInstanceRenderElement3D.MaxInstanceCount * 4 * 4);
                            instanceLightMapVertexBuffer.vertexDeclaration = Laya.VertexMesh.instanceLightMapScaleOffsetDeclaration;
                            instanceLightMapVertexBuffer.instanceBuffer = true;
                            vertexArray.push(instanceLightMapVertexBuffer);
                            stateinfo.lightmapScaleOffsetVB = instanceLightMapVertexBuffer;
                        }
                        break;
                    case Laya.BaseRenderType.SimpleSkinRender:
                        let instanceSimpleAnimatorBuffer = new Laya.WebGLVertexBuffer(Laya.BufferTargetType.ARRAY_BUFFER, Laya.BufferUsage.Dynamic);
                        instanceSimpleAnimatorBuffer.setDataLength(WebGLInstanceRenderElement3D.MaxInstanceCount * 4 * 4);
                        instanceSimpleAnimatorBuffer.vertexDeclaration = Laya.VertexMesh.instanceSimpleAnimatorDeclaration;
                        instanceSimpleAnimatorBuffer.instanceBuffer = true;
                        vertexArray.push(instanceSimpleAnimatorBuffer);
                        stateinfo.simpleAnimatorVB = instanceSimpleAnimatorBuffer;
                        break;
                }
                stateinfo.state.applyState(vertexArray, geometry.bufferState._bindedIndexBuffer);
                WebGLInstanceRenderElement3D._instanceBufferStateMap.set(geometry._id, stateinfo);
            }
            return stateinfo;
        }
        _instanceBufferCreate(length) {
            let array = this._bufferPool.get(length);
            if (!array) {
                this._bufferPool.set(length, []);
                array = this._bufferPool.get(length);
            }
            let element = array.pop() || new Float32Array(length);
            return element;
        }
        constructor() {
            super();
            this._bufferPool = new Map();
            this._vertexBuffers = [];
            this._updateData = [];
            this._updateDataNum = [];
            this.instanceElementList = new Laya.FastSinglelist();
            this.drawCount = 0;
            this.updateNums = 0;
            this.isRender = true;
        }
        addUpdateData(vb, elementLength, maxInstanceCount) {
            this._vertexBuffers[this.updateNums] = vb;
            this._updateDataNum[this.updateNums] = elementLength;
            let data = this._updateData[this.updateNums] = this._instanceBufferCreate(elementLength * maxInstanceCount);
            this.updateNums++;
            return data;
        }
        _compileShader(context) {
            let passes = this._subShader._passes;
            let renderCount = 0;
            for (let i = 0; i < passes.length; i++) {
                let pass = passes[i];
                if (pass.pipelineMode != context.pipelineMode)
                    continue;
                if (this.renderShaderData) {
                    pass.nodeCommonMap = this.owner._commonUniformMap;
                }
                else {
                    pass.nodeCommonMap = null;
                }
                pass.additionShaderData = null;
                if (this.owner) {
                    pass.additionShaderData = this.owner._additionShaderDataKeys;
                }
                let comDef = this._getShaderInstanceDefines(context);
                comDef.add(Laya.MeshSprite3DShaderDeclaration.SHADERDEFINE_GPU_INSTANCE);
                let shaderIns = pass.withCompile(comDef);
                this._curDrawCacheInfo.shaderInss[renderCount] = shaderIns;
                renderCount++;
            }
            this._curDrawCacheInfo.shaderInss.length = renderCount;
        }
        _preUpdatePre(context) {
            super._preUpdatePre(context);
            this._updateInstanceData();
        }
        _updateInstanceData() {
            switch (this.owner.renderNodeType) {
                case Laya.BaseRenderType.MeshRender: {
                    let worldMatrixData = this.addUpdateData(this._instanceStateInfo.worldInstanceVB, 20, WebGLInstanceRenderElement3D.MaxInstanceCount);
                    var insBatches = this.instanceElementList;
                    var elements = insBatches.elements;
                    var count = insBatches.length;
                    this.drawCount = count;
                    this.geometry.instanceCount = this.drawCount;
                    for (var i = 0; i < count; i++) {
                        worldMatrixData.set(elements[i].transform.worldMatrix.elements, i * 20);
                        elements[i].owner._worldParams.writeTo(worldMatrixData, i * 20 + 16);
                    }
                    let haveLightMap = this.renderShaderData.hasDefine(Laya.RenderableSprite3D.SAHDERDEFINE_LIGHTMAP) && this.renderShaderData.hasDefine(Laya.MeshSprite3DShaderDeclaration.SHADERDEFINE_UV1);
                    if (haveLightMap) {
                        let lightMapData = this.addUpdateData(this._instanceStateInfo.lightmapScaleOffsetVB, 4, WebGLInstanceRenderElement3D.MaxInstanceCount);
                        for (var i = 0; i < count; i++) {
                            let lightmapScaleOffset = elements[i].owner.lightmapScaleOffset;
                            var offset = i * 4;
                            lightMapData[offset] = lightmapScaleOffset.x;
                            lightMapData[offset + 1] = lightmapScaleOffset.y;
                            lightMapData[offset + 2] = lightmapScaleOffset.z;
                            lightMapData[offset + 3] = lightmapScaleOffset.w;
                        }
                    }
                    break;
                }
                case Laya.BaseRenderType.SimpleSkinRender: {
                    let worldMatrixData = this.addUpdateData(this._instanceStateInfo.worldInstanceVB, 20, WebGLInstanceRenderElement3D.MaxInstanceCount);
                    var insBatches = this.instanceElementList;
                    var elements = insBatches.elements;
                    var count = insBatches.length;
                    this.drawCount = count;
                    this.geometry.instanceCount = this.drawCount;
                    for (var i = 0; i < count; i++) {
                        worldMatrixData.set(elements[i].transform.worldMatrix.elements, i * 20);
                        elements[i].owner._worldParams.writeTo(worldMatrixData, i * 20 + 16);
                    }
                    let simpleAnimatorData = this.addUpdateData(this._instanceStateInfo.simpleAnimatorVB, 4, WebGLInstanceRenderElement3D.MaxInstanceCount);
                    for (var i = 0; i < count; i++) {
                        var simpleAnimatorParams = elements[i].renderShaderData.getVector(Laya.SimpleSkinnedMeshSprite3D.SIMPLE_SIMPLEANIMATORPARAMS);
                        var offset = i * 4;
                        simpleAnimatorData[offset] = simpleAnimatorParams.x;
                        simpleAnimatorData[offset + 1] = simpleAnimatorParams.y;
                        simpleAnimatorData[offset + 2] = simpleAnimatorParams.z;
                        simpleAnimatorData[offset + 3] = simpleAnimatorParams.w;
                    }
                    break;
                }
            }
        }
        setGeometry(geometry) {
            if (!this.geometry) {
                this.geometry = new Laya.WebGLRenderGeometryElement(geometry.mode, geometry.drawType);
            }
            geometry.cloneTo(this.geometry);
            this.geometry.drawType = Laya.DrawType.DrawElementInstance;
            this._instanceStateInfo = WebGLInstanceRenderElement3D.getInstanceBufferState(geometry, this.owner.renderNodeType, this.renderShaderData._defineDatas);
            this.geometry.bufferState = this._instanceStateInfo.state;
        }
        _render(context) {
            for (let i = 0; i < this.updateNums; i++) {
                let buffer = this._vertexBuffers[i];
                if (!buffer)
                    break;
                let data = this._updateData[i];
                buffer.orphanStorage();
                buffer.setData(data.buffer, 0, 0, this.drawCount * this._updateDataNum[i] * 4);
            }
            super._render(context);
            this.clearRenderData();
        }
        clearRenderData() {
            this.drawCount = 0;
            this.updateNums = 0;
            this._vertexBuffers.length = 0;
            this._updateData.forEach((data) => {
                this._bufferPool.get(data.length).push(data);
            });
            this._updateData.length = 0;
            this._updateDataNum.length = 0;
        }
        destroy() {
            this._bufferPool.clear();
            super.destroy();
        }
    }
    WebGLInstanceRenderElement3D._instanceBufferStateMap = new Map();
    WebGLInstanceRenderElement3D.MaxInstanceCount = 1024;

    class BatchMark {
        constructor() {
            this.updateMark = -1;
            this.indexInList = -1;
            this.batched = false;
            this._curBindElementIndex = 0;
            this._cacheRenderElement = [];
        }
        release() {
            for (var i = 0; i < this._cacheRenderElement.length; i++) {
                this._cacheRenderElement[i].destroy();
            }
            this._cacheRenderElement = null;
        }
    }
    class WebGLBatchQueue {
        constructor(createTransList) {
            this.opaqueCustomSort = false;
            this.transCustomSort = false;
            this.opaqueQueue = new RenderListQueue(false);
            this.opaqueList = this.opaqueQueue.elements;
            if (createTransList) {
                this.transparentQueue = new RenderListQueue(true);
                this.transparentList = this.transparentQueue.elements;
            }
        }
        clearList() {
            this.opaqueList.length = 0;
            this.transparentList && (this.transparentList.length = 0);
        }
        release() {
            if (this.transparentList) {
                this.transparentQueue.destroy();
                this.transparentList = null;
            }
            this.opaqueQueue.destroy();
            this.opaqueList = null;
        }
    }
    class WebGLMeshRenderBatchAgent {
        constructor() {
            this._batchOpaqueMarks = [];
            this._updateCountMark = 0;
            this._mainBatchQueue = new Laya.FastSinglelist();
            this._shadowBatchQueue = new Laya.FastSinglelist();
            this._spotBatchQueue = new Laya.FastSinglelist();
            this._list = new Laya.SingletonList();
            this._baseRenderList = new Laya.SingletonList();
        }
        _canBatch(element) {
            var _a;
            return element.materialRenderQueue < 2500 && element.canDynamicBatch && ((_a = element.subShader) === null || _a === void 0 ? void 0 : _a._owner._enableInstancing);
        }
        _getBatchMark(element) {
            const renderNode = element.owner;
            const geometry = element.geometry;
            const invertFrontFace = element.transform ? element.transform._isFrontFaceInvert : false;
            const invertFrontFaceFlag = invertFrontFace ? 1 : 0;
            const receiveShadowFlag = renderNode.receiveShadow ? 1 : 0;
            const geometryFlag = geometry._id;
            const materialFlag = element.materialId;
            const renderId = (materialFlag << 17) + (geometryFlag << 2) + (invertFrontFaceFlag << 1) + (receiveShadowFlag);
            const reflectFlag = (renderNode.probeReflection ? renderNode.probeReflection._id : -1) + 1;
            const lightmapFlag = renderNode.lightmapIndex + 1;
            const lightProbeFlag = (renderNode.volumetricGI ? renderNode.volumetricGI._id : -1) + 1;
            const giId = (reflectFlag << 10) + (lightmapFlag << 20) + lightProbeFlag;
            const data = this._batchOpaqueMarks[renderId] || (this._batchOpaqueMarks[renderId] = {});
            return data[giId] || (data[giId] = new BatchMark());
        }
        _changeBatchMark(renderNode) {
            let elements = renderNode.renderelements;
            for (var i = 0; i < elements.length; i++) {
                let element = elements[i];
                if (this._canBatch(element)) {
                    let mark = this._getBatchMark(elements[i]);
                    element.customData = mark;
                }
                else {
                    element.customData = null;
                }
            }
        }
        _opaqueInstanceBatch(elements) {
            const elementCount = elements.length;
            const elementArray = elements.elements;
            elements.length = 0;
            this._updateCountMark++;
            for (let i = 0; i < elementCount; i++) {
                const element = elementArray[i];
                if (element.customData) {
                    const instanceMark = element.customData;
                    if (this._updateCountMark == instanceMark.updateMark) {
                        const instanceIndex = instanceMark.indexInList;
                        if (instanceMark.batched) {
                            const originElement = elementArray[instanceIndex];
                            const instanceElements = originElement.instanceElementList;
                            if (instanceElements.length === WebGLInstanceRenderElement3D.MaxInstanceCount) {
                                instanceMark.indexInList = elements.length;
                                instanceMark.batched = false;
                                instanceMark._curBindElementIndex++;
                                elements.add(element);
                            }
                            else {
                                instanceElements.add(element);
                            }
                        }
                        else {
                            const originElement = elementArray[instanceIndex];
                            if (!instanceMark._cacheRenderElement[instanceMark._curBindElementIndex]) {
                                instanceMark._cacheRenderElement[instanceMark._curBindElementIndex] = new WebGLInstanceRenderElement3D();
                            }
                            const instanceRenderElement = instanceMark._cacheRenderElement[instanceMark._curBindElementIndex];
                            instanceRenderElement.subShader = element.subShader;
                            instanceRenderElement.materialShaderData = element.materialShaderData;
                            instanceRenderElement.materialRenderQueue = element.materialRenderQueue;
                            instanceRenderElement.renderShaderData = element.renderShaderData;
                            instanceRenderElement.owner = element.owner;
                            instanceRenderElement.setGeometry(element.geometry);
                            const list = instanceRenderElement.instanceElementList;
                            list.length = 0;
                            list.add(originElement);
                            list.add(element);
                            elementArray[instanceIndex] = instanceRenderElement;
                            instanceMark.batched = true;
                        }
                    }
                    else {
                        instanceMark.updateMark = this._updateCountMark;
                        instanceMark.indexInList = elements.length;
                        instanceMark.batched = false;
                        instanceMark._curBindElementIndex = 0;
                        elements.add(element);
                    }
                }
                else {
                    elements.add(element);
                }
            }
        }
        _transparentInstanceBatch(element) {
        }
        create() {
        }
        addRenderNode(object) {
            this._list.add(object);
            let baseNode = object._baseRenderNode;
            this._baseRenderList.add(baseNode);
            this._changeBatchMark(baseNode);
            return true;
        }
        removeRenderNode(object) {
            this._list.remove(object);
            this._baseRenderList.remove(object._baseRenderNode);
            return true;
        }
        updateProperty(object, property) {
            this._changeBatchMark(object._baseRenderNode);
        }
        setCullCamera(cameraCullInfo) {
            if (cameraCullInfo.length > this._mainBatchQueue.length) {
                let createCount = cameraCullInfo.length - this._mainBatchQueue.length;
                for (var i = 0; i < createCount; i++) {
                    this._mainBatchQueue.add(new WebGLBatchQueue(true));
                }
            }
            else {
                this._mainBatchQueue.length = cameraCullInfo.length;
            }
            this._cameraCullInfo = cameraCullInfo;
        }
        setDirLightCullInfo(directLightCullInfo) {
            if (directLightCullInfo.length > this._shadowBatchQueue.length) {
                let createCount = directLightCullInfo.length - this._shadowBatchQueue.length;
                for (var i = 0; i < createCount; i++) {
                    this._shadowBatchQueue.add(new WebGLBatchQueue(false));
                }
            }
            else {
                this._shadowBatchQueue.length = directLightCullInfo.length;
            }
            this._dirShadowCullInfo = directLightCullInfo;
        }
        setSpotCullingDir(spotCullInfo) {
            if (spotCullInfo.length > this._spotBatchQueue.length) {
                let createCount = spotCullInfo.length - this._spotBatchQueue.length;
                for (var i = 0; i < createCount; i++) {
                    this._spotBatchQueue.add(new WebGLBatchQueue(false));
                }
            }
            else {
                this._spotBatchQueue.length = spotCullInfo.length;
            }
            this._spotCullInfo = spotCullInfo;
        }
        appendRenderElement(cullMode, cullInfoIndex, context) {
            let moduleBatchQueue;
            let cullInfo;
            switch (cullMode) {
                case Laya.BatchCullMode.Camera:
                    cullInfo = this._cameraCullInfo[cullInfoIndex];
                    moduleBatchQueue = this._mainBatchQueue.elements[cullInfoIndex];
                    moduleBatchQueue.clearList();
                    RenderCullUtil.cullByCameraCullInfo(cullInfo, this._baseRenderList.elements, this._list.length, moduleBatchQueue.opaqueQueue, moduleBatchQueue.transparentQueue, context);
                    this._opaqueInstanceBatch(moduleBatchQueue.opaqueList);
                    break;
                case Laya.BatchCullMode.DirectLight:
                    cullInfo = this._dirShadowCullInfo[cullInfoIndex];
                    moduleBatchQueue = this._shadowBatchQueue.elements[cullInfoIndex];
                    moduleBatchQueue.clearList();
                    RenderCullUtil.cullDirectLightShadow(cullInfo, this._baseRenderList.elements, this._list.length, moduleBatchQueue.opaqueQueue, context);
                    this._opaqueInstanceBatch(moduleBatchQueue.opaqueList);
                    break;
                case Laya.BatchCullMode.Spot:
                    cullInfo = this._spotCullInfo[cullInfoIndex];
                    moduleBatchQueue = this._spotBatchQueue.elements[cullInfoIndex];
                    moduleBatchQueue.clearList();
                    RenderCullUtil.cullSpotShadow(cullInfo, this._baseRenderList.elements, this._list.length, moduleBatchQueue.opaqueQueue, context);
                    this._opaqueInstanceBatch(moduleBatchQueue.opaqueList);
                    break;
            }
            return moduleBatchQueue;
        }
        release() {
            for (var [key, value] of WebGLInstanceRenderElement3D._instanceBufferStateMap) {
                value.state.destroy();
                value.worldInstanceVB && value.worldInstanceVB.destroy();
                value.lightmapScaleOffsetVB && value.lightmapScaleOffsetVB.destroy();
                value.simpleAnimatorVB && value.simpleAnimatorVB.destroy();
            }
            WebGLInstanceRenderElement3D._instanceBufferStateMap.clear();
            const baseRenderArray = this._baseRenderList.elements;
            for (let i = 0, n = this._baseRenderList.length; i < n; i++) {
                const renderNode = baseRenderArray[i];
                if (!renderNode)
                    continue;
                const elements = renderNode.renderelements;
                if (!elements)
                    continue;
                for (let j = 0, m = elements.length; j < m; j++) {
                    elements[j] && (elements[j].customData = null);
                }
            }
            this._list.clear();
            this._list = null;
            this._baseRenderList.clear();
            this._baseRenderList = null;
            for (var i in this._batchOpaqueMarks) {
                let map = this._batchOpaqueMarks[i];
                for (var j in map) {
                    map[j].release();
                }
                map = null;
            }
            this._batchOpaqueMarks = null;
            this._cameraCullInfo = null;
            this._dirShadowCullInfo = null;
            this._spotCullInfo = null;
            for (let i = 0, n = this._mainBatchQueue.length; i < n; i++) {
                this._mainBatchQueue.elements[i].release();
            }
            this._mainBatchQueue.clear();
            this._mainBatchQueue = null;
            for (let i = 0, n = this._shadowBatchQueue.length; i < n; i++) {
                this._shadowBatchQueue.elements[i].release();
            }
            this._shadowBatchQueue.clear();
            this._shadowBatchQueue = null;
            for (let i = 0, n = this._spotBatchQueue.length; i < n; i++) {
                this._spotBatchQueue.elements[i].release();
            }
            this._spotBatchQueue.clear();
            this._spotBatchQueue = null;
        }
    }

    class WebGLDrawNodeCMDData extends Laya.DrawNodeCMDData {
        get node() {
            return this._node;
        }
        set node(value) {
            this._node = value;
        }
        get destShaderData() {
            return this._destShaderData;
        }
        set destShaderData(value) {
            this._destShaderData = value;
        }
        get destSubShader() {
            return this._destSubShader;
        }
        set destSubShader(value) {
            this._destSubShader = value;
        }
        get subMeshIndex() {
            return this._subMeshIndex;
        }
        set subMeshIndex(value) {
            this._subMeshIndex = value;
        }
        constructor() {
            super();
            this.type = Laya.RenderCMDType.DrawNode;
        }
        apply(context) {
            if (this.destShaderData && this.destSubShader) {
                this.node._renderUpdatePre(context);
                if (this.subMeshIndex == -1) {
                    this.node.renderelements.forEach(element => {
                        let oriSubShader = element.subShader;
                        let oriMatShaderData = element.materialShaderData;
                        element.subShader = this._destSubShader;
                        element.materialShaderData = this._destShaderData;
                        context.drawRenderElementOne(element);
                        element.subShader = oriSubShader;
                        element.materialShaderData = oriMatShaderData;
                    });
                }
                else {
                    let element = this.node.renderelements[this.subMeshIndex];
                    let oriSubShader = element.subShader;
                    let oriMatShaderData = element.materialShaderData;
                    element.subShader = this._destSubShader;
                    element.materialShaderData = this._destShaderData;
                    context.drawRenderElementOne(element);
                    element.subShader = oriSubShader;
                    element.materialShaderData = oriMatShaderData;
                }
            }
        }
    }
    class WebGLBlitQuadCMDData extends Laya.BlitQuadCMDData {
        get dest() {
            return this._dest;
        }
        set dest(value) {
            this._dest = value;
        }
        get viewport() {
            return this._viewport;
        }
        set viewport(value) {
            value.cloneTo(this._viewport);
        }
        get scissor() {
            return this._scissor;
        }
        set scissor(value) {
            value.cloneTo(this._scissor);
        }
        get source() {
            return this._source;
        }
        set source(value) {
            this._source = value;
            if (this._source) {
                this._sourceTexelSize.setValue(1.0 / this._source.width, 1.0 / this._source.height, this._source.width, this._source.height);
            }
        }
        get offsetScale() {
            return this._offsetScale;
        }
        set offsetScale(value) {
            value.cloneTo(this._offsetScale);
        }
        get element() {
            return this._element;
        }
        set element(value) {
            this._element = value;
        }
        constructor() {
            super();
            this.type = Laya.RenderCMDType.Blit;
            this._viewport = new Laya.Viewport();
            this._scissor = new Laya.Vector4();
            this._offsetScale = new Laya.Vector4();
            this._sourceTexelSize = new Laya.Vector4();
        }
        apply(context) {
            this.element.materialShaderData._setInternalTexture(Laya.Command.SCREENTEXTURE_ID, this._source);
            this.element.materialShaderData.setVector(Laya.Command.SCREENTEXTUREOFFSETSCALE_ID, this._offsetScale);
            this.element.materialShaderData.setVector(Laya.Command.MAINTEXTURE_TEXELSIZE_ID, this._sourceTexelSize);
            context.setViewPort(this._viewport);
            context.setScissor(this._scissor);
            context.setRenderTarget(this.dest, Laya.RenderClearFlag.Nothing);
            context.drawRenderElementOne(this.element);
        }
    }
    class WebGLDrawElementCMDData extends Laya.DrawElementCMDData {
        constructor() {
            super();
            this.type = Laya.RenderCMDType.DrawElement;
        }
        setRenderelements(value) {
            this._elemets = value;
        }
        apply(context) {
            if (this._elemets.length == 1) {
                context.drawRenderElementOne(this._elemets[0]);
            }
            else {
                this._elemets.forEach(element => {
                    context.drawRenderElementOne(element);
                });
            }
        }
    }
    class WebGLSetViewportCMD extends Laya.SetViewportCMD {
        get viewport() {
            return this._viewport;
        }
        set viewport(value) {
            this._viewport = value;
        }
        get scissor() {
            return this._scissor;
        }
        set scissor(value) {
            this._scissor = value;
        }
        constructor() {
            super();
            this.type = Laya.RenderCMDType.ChangeViewPort;
            this.scissor = new Laya.Vector4();
            this.viewport = new Laya.Viewport();
        }
        apply(context) {
            context.setViewPort(this.viewport);
            context.setScissor(this.scissor);
        }
    }
    const viewport = new Laya.Viewport();
    const scissor = new Laya.Vector4();
    class WebGLSetRenderTargetCMD extends Laya.SetRenderTargetCMD {
        get rt() {
            return this._rt;
        }
        set rt(value) {
            this._rt = value;
        }
        get clearFlag() {
            return this._clearFlag;
        }
        set clearFlag(value) {
            this._clearFlag = value;
        }
        get clearColorValue() {
            return this._clearColorValue;
        }
        set clearColorValue(value) {
            value.cloneTo(this._clearColorValue);
        }
        get clearDepthValue() {
            return this._clearDepthValue;
        }
        set clearDepthValue(value) {
            this._clearDepthValue = value;
        }
        get clearStencilValue() {
            return this._clearStencilValue;
        }
        set clearStencilValue(value) {
            this._clearStencilValue = value;
        }
        constructor() {
            super();
            this.type = Laya.RenderCMDType.ChangeRenderTarget;
            this._clearColorValue = new Laya.Color();
        }
        apply(context) {
            context.setRenderTarget(this.rt, Laya.RenderClearFlag.Nothing);
            context.setClearData(this.clearFlag, this.clearColorValue, this.clearDepthValue, this.clearStencilValue);
            if (this.rt) {
                viewport.set(0, 0, this.rt._textures[0].width, this.rt._textures[0].height);
                scissor.setValue(0, 0, this.rt._textures[0].width, this.rt._textures[0].height);
                context.setViewPort(viewport);
                context.setScissor(scissor);
            }
        }
    }

    class WebGLRenderContext3D {
        get sceneData() {
            return this._sceneData;
        }
        set sceneData(value) {
            this._sceneData = value;
            if (Laya.Config._uniformBlock && this.sceneData) ;
        }
        get cameraData() {
            return this._cameraData;
        }
        set cameraData(value) {
            this._cameraData = value;
        }
        get sceneModuleData() {
            return this._sceneModuleData;
        }
        set sceneModuleData(value) {
            this._sceneModuleData = value;
        }
        get cameraModuleData() {
            return this._cameraModuleData;
        }
        set cameraModuleData(value) {
            this._cameraModuleData = value;
        }
        get globalShaderData() {
            return this._globalShaderData;
        }
        set globalShaderData(value) {
            this._globalShaderData = value;
        }
        globalComkeyToID(name) {
            if (this._globalComkeyNameMap[name] !== undefined) {
                return this._globalComkeyNameMap[name];
            }
            else {
                const id = this._globalComkeyCounter++;
                this._globalComkeyNameMap[name] = id;
                return id;
            }
        }
        _getSceneCameraCacheKey() {
            let key = `${this.sceneData ? this.sceneData._id : -1} + ${this.cameraData ? this.cameraData._id : -1}+${this._pipelineMode}`;
            this._curRenderGlobalKey = this.globalComkeyToID(key);
            if (!this._globalRendercacheInfoMap.has(this._curRenderGlobalKey)) {
                let cacheInfo = new Laya.WebGLGlobalPipeLineCacheInfo();
                this._curRenderCacheInfo = cacheInfo;
                this._cacheGlobalDefines.cloneTo(cacheInfo.globalDefineData);
                this._curRenderCacheInfo.globalDefineChangeFlag.setValue(Laya.Stat.loopCount, Laya.WebGLEngine.instance._framePassCount);
                this._globalRendercacheInfoMap.set(this._curRenderGlobalKey, cacheInfo);
            }
            else {
                this._curRenderCacheInfo = this._globalRendercacheInfoMap.get(this._curRenderGlobalKey);
                if (!this._curRenderCacheInfo.globalDefineData.isEual(this._cacheGlobalDefines)) {
                    this._cacheGlobalDefines.cloneTo(this._curRenderCacheInfo.globalDefineData);
                    this._curRenderCacheInfo.globalDefineChangeFlag.setValue(Laya.Stat.loopCount, Laya.WebGLEngine.instance._framePassCount);
                }
            }
            this._curDefineChangeFlag = this._curRenderCacheInfo.globalDefineChangeFlag;
        }
        _getContextShaderDefines() {
            return this._cacheGlobalDefines;
        }
        _prepareContext() {
            let contextDef = this._cacheGlobalDefines;
            if (this.sceneData) {
                this.sceneData._defineDatas.cloneTo(contextDef);
                if (Laya.Config._uniformBlock) {
                    for (let key of this.preDrawUniformMaps) {
                        let uniformMap = Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap(key);
                        if (uniformMap._idata.size > 0) {
                            this.sceneData.createUniformBuffer(key, uniformMap._idata, true);
                        }
                    }
                }
            }
            else {
                this._globalConfigShaderData.cloneTo(contextDef);
            }
            if (this.cameraData) {
                contextDef.addDefineDatas(this.cameraData._defineDatas);
                if (Laya.Config._uniformBlock) {
                    let cameraMap = Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap("BaseCamera");
                    this.cameraData.createUniformBuffer("BaseCamera", cameraMap._idata, true);
                }
            }
            this._getSceneCameraCacheKey();
        }
        setRenderTarget(value, clearFlag) {
            this._clearFlag = clearFlag;
            if (value == this._renderTarget)
                return;
            this._renderTarget = value;
            this._needStart = true;
        }
        setViewPort(value) {
            this._viewPort = value;
            this._needStart = true;
        }
        setScissor(value) {
            this._scissor = value;
            this._needStart = true;
        }
        get sceneUpdateMask() {
            return this._sceneUpdateMask;
        }
        set sceneUpdateMask(value) {
            this._sceneUpdateMask = value;
        }
        get cameraUpdateMask() {
            return this._cameraUpdateMask;
        }
        set cameraUpdateMask(value) {
            this._cameraUpdateMask = value;
        }
        get pipelineMode() {
            return this._pipelineMode;
        }
        set pipelineMode(value) {
            this._pipelineMode = value;
        }
        get invertY() {
            return this._invertY;
        }
        set invertY(value) {
            this._invertY = value;
        }
        constructor() {
            this._cacheGlobalDefines = new Laya.WebDefineDatas();
            this._sceneUpdateMask = 0;
            this._cameraUpdateMask = 0;
            this._needStart = true;
            this._globalComkeyNameMap = {};
            this._globalComkeyCounter = 0;
            this._globalRendercacheInfoMap = new Map();
            this._clearColor = new Laya.Color();
            this._globalConfigShaderData = Laya.Shader3D._configDefineValues;
            this.preDrawUniformMaps = new Set();
            this.cameraUpdateMask = 0;
            WebGLRenderContext3D._instance = this;
        }
        runOneCMD(cmd) {
            cmd.apply(this);
        }
        runCMDList(cmds) {
            cmds.forEach(element => {
                element.apply(this);
            });
        }
        setClearData(clearFlag, color, depth, stencil) {
            this._clearFlag = clearFlag;
            color.cloneTo(this._clearColor);
            this._clearDepth = depth;
            this._clearStencil = stencil;
            return 0;
        }
        drawRenderElementList(list) {
            if (this._needStart) {
                this._bindRenderTarget();
                this._start();
                this._needStart = false;
            }
            let time = performance.now();
            this._prepareContext();
            let elements = list.elements;
            for (var i = 0, n = list.length; i < n; i++) {
                elements[i]._preUpdatePre(this);
            }
            let bufferMgr = Laya.WebGLEngine.instance.bufferMgr;
            if (bufferMgr) {
                bufferMgr.upload();
            }
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_3DContextPre, performance.now() - time);
            time = performance.now();
            Laya.WebGLEngine.instance._GLRenderState.clearRenderStateCache();
            for (var i = 0, n = list.length; i < n; i++) {
                elements[i]._render(this);
            }
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_3DContextRender, performance.now() - time);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_3DDrawCall, list.length);
            Laya.LayaGL.renderEngine._framePassCount++;
            return 0;
        }
        drawRenderElementOne(node) {
            if (this._needStart) {
                this._bindRenderTarget();
                this._start();
                this._needStart = false;
            }
            this._prepareContext();
            node._preUpdatePre(this);
            let bufferMgr = Laya.WebGLEngine.instance.bufferMgr;
            if (bufferMgr) {
                bufferMgr.upload();
            }
            Laya.WebGLEngine.instance._GLRenderState.clearRenderStateCache();
            node._render(this);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_3DDrawCall, 1);
            Laya.LayaGL.renderEngine._framePassCount++;
            return 0;
        }
        _bindRenderTarget() {
            if (this._renderTarget) {
                Laya.LayaGL.textureContext.bindRenderTarget(this._renderTarget);
            }
            else {
                Laya.LayaGL.textureContext.bindoutScreenTarget();
            }
        }
        _start() {
            Laya.WebGLEngine.instance.scissorTest(true);
            Laya.WebGLEngine.instance.viewport(this._viewPort.x, this._viewPort.y, this._viewPort.width, this._viewPort.height);
            Laya.WebGLEngine.instance.scissor(this._viewPort.x, this._viewPort.y, this._viewPort.width, this._viewPort.height);
            if (this._clearFlag != Laya.RenderClearFlag.Nothing)
                Laya.WebGLEngine.instance.clearRenderTexture(this._clearFlag, this._clearColor, this._clearDepth, this._clearStencil);
            Laya.WebGLEngine.instance.scissor(this._scissor.x, this._scissor.y, this._scissor.z, this._scissor.w);
        }
        clearRenderTarget() {
            this._bindRenderTarget();
            this._start();
        }
    }

    class WebGLSkinRenderElement3D extends WebGLRenderElement3D {
        constructor() {
            super();
        }
        drawGeometry(shaderIns) {
            let element = this.geometry.drawParams.elements;
            if (!this.skinnedData)
                return;
            this.geometry.bufferState.bind();
            let shaderVariable = shaderIns._cacheShaerVariable[Laya.SkinnedMeshRenderer.BONES];
            if (!shaderVariable) {
                for (var i = 0, n = shaderIns._spriteUniformParamsMap._idata.length; i < n; i++) {
                    if (shaderIns._spriteUniformParamsMap._idata[i].dataOffset == Laya.SkinnedMeshRenderer.BONES) {
                        shaderVariable = shaderIns._spriteUniformParamsMap._idata[i];
                        shaderIns._cacheShaerVariable[Laya.SkinnedMeshRenderer.BONES] = shaderVariable;
                        break;
                    }
                }
            }
            for (var j = 0, m = this.geometry.drawParams.length / 2; j < m; j++) {
                var subSkinnedDatas = this.skinnedData[j];
                Laya.WebGLEngine.instance.uploadOneUniforms(shaderIns._renderShaderInstance, shaderVariable, subSkinnedDatas);
                var offset = j * 2;
                Laya.WebGLEngine.instance.getDrawContext().drawElements(this.geometry._glmode, element[offset + 1], this.geometry._glindexFormat, element[offset]);
                Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_DrawCall, 1);
            }
        }
    }

    WebBaseRenderNode.BaseRenderNodeClass = WebBaseRenderNode;
    class WebGL3DRenderPassFactory {
        createMeshRenderBatchModule() {
            return new WebGLMeshRenderBatchAgent();
        }
        createSimpleSkinRenderBatchModule() {
            return new WebGLMeshRenderBatchAgent();
        }
        createSetRenderDataCMD() {
            return new Laya.WebGLSetRenderData();
        }
        createSetShaderDefineCMD() {
            return new Laya.WebGLSetShaderDefine();
        }
        createDrawNodeCMDData() {
            return new WebGLDrawNodeCMDData();
        }
        createBlitQuadCMDData() {
            return new WebGLBlitQuadCMDData();
        }
        createDrawElementCMDData() {
            return new WebGLDrawElementCMDData();
        }
        createSetViewportCMD() {
            return new WebGLSetViewportCMD();
        }
        createSetRenderTargetCMD() {
            return new WebGLSetRenderTargetCMD();
        }
        createSceneRenderManager() {
            return new WebSceneRenderManager();
        }
        createSkinRenderElement() {
            return new WebGLSkinRenderElement3D();
        }
        createRenderContext3D() {
            let context = new WebGLRenderContext3D();
            return context;
        }
        createRenderElement3D() {
            return new WebGLRenderElement3D();
        }
        createRender3DProcess() {
            let renderPass = new WebRender3DProcess();
            let forwardRP = renderPass._renderPass = new WebForwardAddRP();
            forwardRP.mainRenderpass = new WebForwardAddClusterRP();
            forwardRP.dirShadowRenderPass = new WebDirCascadeShadowRP();
            forwardRP.spotShadowRenderPass = new WebBaseSpotRP();
            return renderPass;
        }
    }
    Laya.Laya.addBeforeInitCallback(() => {
        if (!Laya.Laya3DRender.Render3DPassFactory)
            Laya.Laya3DRender.Render3DPassFactory = new WebGL3DRenderPassFactory();
    });

    exports.BatchMark = BatchMark;
    exports.RenderCullUtil = RenderCullUtil;
    exports.RenderListQueue = RenderListQueue;
    exports.RenderPassUtil = RenderPassUtil;
    exports.RenderQuickSort = RenderQuickSort;
    exports.Web3DRenderModuleFactory = Web3DRenderModuleFactory;
    exports.WebBaseRenderNode = WebBaseRenderNode;
    exports.WebBaseSpotRP = WebBaseSpotRP;
    exports.WebCameraNodeData = WebCameraNodeData;
    exports.WebDirCascadeShadowRP = WebDirCascadeShadowRP;
    exports.WebDirectLight = WebDirectLight;
    exports.WebForwardAddClusterRP = WebForwardAddClusterRP;
    exports.WebForwardAddRP = WebForwardAddRP;
    exports.WebGL3DRenderPassFactory = WebGL3DRenderPassFactory;
    exports.WebGLBatchQueue = WebGLBatchQueue;
    exports.WebGLBlitQuadCMDData = WebGLBlitQuadCMDData;
    exports.WebGLDrawElementCMDData = WebGLDrawElementCMDData;
    exports.WebGLDrawNodeCMDData = WebGLDrawNodeCMDData;
    exports.WebGLInstanceRenderElement3D = WebGLInstanceRenderElement3D;
    exports.WebGLMeshRenderBatchAgent = WebGLMeshRenderBatchAgent;
    exports.WebGLRenderContext3D = WebGLRenderContext3D;
    exports.WebGLRenderElement3D = WebGLRenderElement3D;
    exports.WebGLSetRenderTargetCMD = WebGLSetRenderTargetCMD;
    exports.WebGLSetViewportCMD = WebGLSetViewportCMD;
    exports.WebGLSkinRenderElement3D = WebGLSkinRenderElement3D;
    exports.WebLightmap = WebLightmap;
    exports.WebMeshRenderNode = WebMeshRenderNode;
    exports.WebPointLight = WebPointLight;
    exports.WebReflectionProbe = WebReflectionProbe;
    exports.WebRender3DProcess = WebRender3DProcess;
    exports.WebSceneNodeData = WebSceneNodeData;
    exports.WebSceneRenderManager = WebSceneRenderManager;
    exports.WebSimpleSkinRenderNode = WebSimpleSkinRenderNode;
    exports.WebSkinRenderNode = WebSkinRenderNode;
    exports.WebSpotLight = WebSpotLight;
    exports.WebVolumetricGI = WebVolumetricGI;

})(window.Laya = window.Laya || {}, Laya);
//# sourceMappingURL=laya.webgl_3D.js.map
