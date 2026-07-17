(function (exports, Laya) {
    'use strict';

    class BatchManager {
        static registerProvider(renderType, cls) {
            if (BatchManager.registry[renderType])
                throw new Error("Overlapping batch optimization");
            BatchManager.registry[renderType] = cls;
        }
        static createProvider(renderType) {
            return new (BatchManager.registry[renderType] || NullBatchProvider)();
        }
    }
    BatchManager.registry = {};
    class NullBatchProvider {
        batch(list, start, end, allowReorder) {
            for (let i = start; i <= end; i++)
                list.add(list.elements[i]);
        }
        reset() { }
        destroy() { }
    }

    class SequenceFrame2DInstanceBatch {
        constructor() {
            this._recoverList = new Laya.FastSinglelist();
        }
        static __init__() {
            if (BatchManager.registry[Laya.BaseRender2DType.sequenceFrame2D]) {
                return;
            }
            BatchManager.registerProvider(Laya.BaseRender2DType.sequenceFrame2D, SequenceFrame2DInstanceBatch);
        }
        batch(list, start, end, allowReorder) {
            if (start > end) {
                return;
            }
            const elementArray = list.elements;
            let batchStart = -1;
            let headElement = null;
            let instanceCount = 0;
            for (let i = start; i <= end; i++) {
                const element = elementArray[i];
                const renderer = element._sequenceFrame2DRender;
                const count = renderer ? renderer.activeInstanceCount : 0;
                if (count <= 0) {
                    continue;
                }
                if (batchStart < 0) {
                    batchStart = i;
                    headElement = element;
                    instanceCount = count;
                    continue;
                }
                if (!this.check(headElement, element) || instanceCount + count > SequenceFrame2DInstanceBatchTool.MaxInstanceCount) {
                    this._batchInternal(list, batchStart, i - 1);
                    batchStart = i;
                    headElement = element;
                    instanceCount = count;
                }
                else {
                    instanceCount += count;
                }
            }
            if (batchStart >= 0) {
                this._batchInternal(list, batchStart, end);
            }
        }
        reset() {
            this.recover();
        }
        destroy() {
            this.recover();
            this._recoverList.length = 0;
        }
        check(left, right) {
            const leftRenderer = left._sequenceFrame2DRender;
            const rightRenderer = right._sequenceFrame2DRender;
            if (!leftRenderer || !rightRenderer) {
                return false;
            }
            if (!leftRenderer._canBatchWith(rightRenderer)) {
                return false;
            }
            if (left.materialShaderData !== right.materialShaderData || left.subShader !== right.subShader) {
                return false;
            }
            const leftOwner = left.owner;
            const rightOwner = right.owner;
            if (leftOwner.globalRenderData !== rightOwner.globalRenderData) {
                return false;
            }
            if (leftOwner.getClipInfo && rightOwner.getClipInfo && leftOwner.getClipInfo() !== rightOwner.getClipInfo()) {
                return false;
            }
            return true;
        }
        recover() {
            const recoverArray = this._recoverList.elements;
            for (let i = 0, n = this._recoverList.length; i < n; i++) {
                SequenceFrame2DInstanceBatchTool.recover(recoverArray[i]);
            }
            this._recoverList.length = 0;
        }
        _batchInternal(list, start, end) {
            const elementArray = list.elements;
            const activeElements = [];
            let totalInstanceCount = 0;
            for (let i = start; i <= end; i++) {
                const element = elementArray[i];
                const renderer = element._sequenceFrame2DRender;
                const count = renderer ? renderer.activeInstanceCount : 0;
                if (count > 0) {
                    activeElements.push(element);
                    totalInstanceCount += count;
                }
            }
            if (totalInstanceCount <= 0) {
                return;
            }
            if (activeElements.length === 1) {
                list.add(activeElements[0]);
                return;
            }
            const info = SequenceFrame2DInstanceBatchTool.getBatchInfo();
            this._recoverList.add(info);
            const configHash = this._getConfigHash(activeElements, totalInstanceCount);
            const uploadConfig = !info.configValid || info.configHash !== configHash;
            const firstRenderer = activeElements[0]._sequenceFrame2DRender;
            if (this._isContiguousInstanceIDRange(activeElements)) {
                const firstID = firstRenderer.instanceID;
                firstRenderer._uploadRuntimeDataRange(info.runtimeVB, firstID, totalInstanceCount);
                if (uploadConfig) {
                    firstRenderer._uploadConfigDataRange(info.configVB, firstID, totalInstanceCount);
                    info.configHash = configHash;
                    info.configValid = true;
                }
            }
            else {
                const runtimeStride = Laya.SequenceFrame2DShader.RUNTIME_FLOAT_STRIDE;
                const configStride = Laya.SequenceFrame2DShader.CONFIG_FLOAT_STRIDE;
                const runtimeData = SequenceFrame2DInstanceBatchTool._instanceBufferCreate(runtimeStride * SequenceFrame2DInstanceBatchTool.MaxInstanceCount);
                this._copyRuntimeData(activeElements, runtimeData);
                info.runtimeVB.setData(runtimeData.buffer, 0, 0, totalInstanceCount * runtimeStride * 4);
                SequenceFrame2DInstanceBatchTool._instanceBufferRecover(runtimeData);
                if (uploadConfig) {
                    const configData = SequenceFrame2DInstanceBatchTool._instanceBufferCreate(configStride * SequenceFrame2DInstanceBatchTool.MaxInstanceCount);
                    this._copyConfigData(activeElements, configData);
                    info.configVB.setData(configData.buffer, 0, 0, totalInstanceCount * configStride * 4);
                    SequenceFrame2DInstanceBatchTool._instanceBufferRecover(configData);
                    info.configHash = configHash;
                    info.configValid = true;
                }
            }
            const first = activeElements[0];
            const geometry = info.geometry;
            geometry.instanceCount = totalInstanceCount;
            geometry.indexFormat = first.geometry.indexFormat;
            const batchElement = info.element;
            batchElement.materialShaderData = first.materialShaderData;
            batchElement.value2DShaderData = first.value2DShaderData;
            batchElement.globalShaderData = first.globalShaderData;
            batchElement.subShader = first.subShader;
            batchElement.renderStateIsBySprite = first.renderStateIsBySprite;
            batchElement.nodeCommonMap = first.nodeCommonMap;
            batchElement.owner = first.owner;
            list.add(batchElement);
        }
        _isContiguousInstanceIDRange(activeElements) {
            let expectedID = -1;
            for (let i = 0, n = activeElements.length; i < n; i++) {
                const renderer = activeElements[i]._sequenceFrame2DRender;
                const id = renderer.instanceID;
                const count = renderer.activeInstanceCount;
                if (id < 0 || count <= 0)
                    return false;
                if (expectedID >= 0 && id !== expectedID)
                    return false;
                expectedID = id + count;
            }
            return true;
        }
        _copyRuntimeData(activeElements, target) {
            const stride = Laya.SequenceFrame2DShader.RUNTIME_FLOAT_STRIDE;
            this._copySharedDataRuns(activeElements, target, stride, (sourceRenderer, targetOffset, startID, count) => {
                sourceRenderer._copyRuntimeDataRange(target, targetOffset, startID, count);
            });
        }
        _copyConfigData(activeElements, target) {
            const stride = Laya.SequenceFrame2DShader.CONFIG_FLOAT_STRIDE;
            this._copySharedDataRuns(activeElements, target, stride, (sourceRenderer, targetOffset, startID, count) => {
                sourceRenderer._copyConfigDataRange(target, targetOffset, startID, count);
            });
        }
        _copySharedDataRuns(activeElements, target, stride, copyRun) {
            const sourceRenderer = activeElements[0]._sequenceFrame2DRender;
            let targetOffset = 0;
            let runStartID = -1;
            let runCount = 0;
            let expectedID = -1;
            const flush = () => {
                if (runCount <= 0)
                    return;
                copyRun(sourceRenderer, targetOffset, runStartID, runCount);
                targetOffset += runCount * stride;
                runCount = 0;
            };
            for (let i = 0, n = activeElements.length; i < n; i++) {
                const renderer = activeElements[i]._sequenceFrame2DRender;
                const id = renderer.instanceID;
                const count = renderer.activeInstanceCount;
                if (id < 0 || count <= 0)
                    continue;
                if (runCount > 0 && id === expectedID) {
                    runCount += count;
                    expectedID = id + count;
                    continue;
                }
                flush();
                runStartID = id;
                runCount = count;
                expectedID = id + count;
            }
            flush();
        }
        _getConfigHash(activeElements, totalInstanceCount) {
            let hash = totalInstanceCount | 0;
            for (let i = 0, n = activeElements.length; i < n; i++) {
                const renderer = activeElements[i]._sequenceFrame2DRender;
                hash = Math.imul(hash ^ renderer.instanceID, 16777619);
                hash = Math.imul(hash ^ renderer.getRenderID(), 16777619);
                hash = Math.imul(hash ^ renderer.configVersion, 16777619);
                hash = Math.imul(hash ^ renderer.activeInstanceCount, 16777619);
            }
            return hash;
        }
    }
    class SequenceFrame2DInstanceBatchTool {
        static getBatchInfo() {
            return SequenceFrame2DInstanceBatchTool._batchInfoPool.pop() || SequenceFrame2DInstanceBatchTool.createBatchInfo();
        }
        static createBatchInfo() {
            const element = Laya.LayaGL.render2DRenderPassFactory.createRenderElement2D();
            const geometry = Laya.LayaGL.renderDeviceFactory.createRenderGeometryElement(Laya.MeshTopology.Triangles, Laya.DrawType.DrawElementInstance);
            const state = Laya.LayaGL.renderDeviceFactory.createBufferState();
            const runtimeVB = Laya.LayaGL.renderDeviceFactory.createVertexBuffer(Laya.BufferUsage.Dynamic);
            const configVB = Laya.LayaGL.renderDeviceFactory.createVertexBuffer(Laya.BufferUsage.Dynamic);
            runtimeVB.vertexDeclaration = Laya.SequenceFrame2DShader.runtimeDeclaration;
            runtimeVB.instanceBuffer = true;
            runtimeVB.setDataLength(SequenceFrame2DInstanceBatchTool.MaxInstanceCount * Laya.SequenceFrame2DShader.RUNTIME_FLOAT_STRIDE * 4);
            configVB.vertexDeclaration = Laya.SequenceFrame2DShader.configDeclaration;
            configVB.instanceBuffer = true;
            configVB.setDataLength(SequenceFrame2DInstanceBatchTool.MaxInstanceCount * Laya.SequenceFrame2DShader.CONFIG_FLOAT_STRIDE * 4);
            geometry.bufferState = state;
            geometry.indexFormat = Laya.IndexFormat.UInt16;
            geometry.setDrawElemenParams(6, 0);
            geometry.instanceCount = 0;
            state.applyState([Laya.SequenceFrame2DShader._vbs, runtimeVB, configVB], Laya.SequenceFrame2DShader._ibs);
            element.geometry = geometry;
            element.renderStateIsBySprite = false;
            element.nodeCommonMap = ["BaseRender2D"];
            return {
                element,
                geometry,
                state,
                runtimeVB,
                configVB,
                configHash: -1,
                configValid: false,
            };
        }
        static recover(info) {
            const element = info.element;
            element.materialShaderData = null;
            element.value2DShaderData = null;
            element.globalShaderData = null;
            element.subShader = null;
            element.owner = null;
            element.nodeCommonMap = ["BaseRender2D"];
            info.geometry.clearRenderParams();
            info.geometry.setDrawElemenParams(6, 0);
            info.geometry.instanceCount = 0;
            SequenceFrame2DInstanceBatchTool._batchInfoPool.push(info);
        }
        static _instanceBufferCreate(length) {
            let array = SequenceFrame2DInstanceBatchTool._bufferPool[length];
            if (!array) {
                array = SequenceFrame2DInstanceBatchTool._bufferPool[length] = [];
            }
            return array.pop() || new Float32Array(length);
        }
        static _instanceBufferRecover(float32) {
            const length = float32.length;
            let array = SequenceFrame2DInstanceBatchTool._bufferPool[length];
            if (!array) {
                array = SequenceFrame2DInstanceBatchTool._bufferPool[length] = [];
            }
            array.push(float32);
        }
    }
    SequenceFrame2DInstanceBatchTool.MaxInstanceCount = 4096;
    SequenceFrame2DInstanceBatchTool._batchInfoPool = [];
    SequenceFrame2DInstanceBatchTool._bufferPool = [];
    SequenceFrame2DInstanceBatch.__init__();

    class Web2DGraphicWholeBuffer {
        constructor() {
            this._num = 0;
            this._updateRange = new Laya.Vector2(100000000, -100000000);
        }
        _modifyOneView(view) {
            this._updateRange.y = Math.max(view.start + view.length, this._updateRange.y);
            this._updateRange.x = Math.min(view.start, this._updateRange.x);
        }
        addDataView(view) {
            view._next = null;
            view._prev = null;
            if (!this._first) {
                this._first = view;
            }
            if (this._last) {
                this._last._next = view;
                view._prev = this._last;
            }
            view.owner = this;
            this._last = view;
            this._num++;
        }
        removeDataView(view) {
            view.owner = null;
            if (view._prev) {
                view._prev._next = view._next;
            }
            if (view._next) {
                view._next._prev = view._prev;
            }
            if (view == this._first) {
                this._first = view._next;
            }
            if (view == this._last) {
                this._last = view._prev;
            }
            view._next = null;
            view._prev = null;
            this._updateRange.x = Math.min(view.start, this._updateRange.x);
            this._updateRange.y = Math.max(view.start + view.length, this._updateRange.y);
            this._num--;
        }
        destroy() {
            this._first = null;
            this._last = null;
            this._dataView = null;
            this.arrayBuffer = null;
        }
    }
    class Web2DGraphicsVertexBuffer extends Web2DGraphicWholeBuffer {
        resetData(byteLength) {
            this.arrayBuffer = new ArrayBuffer(byteLength);
            let newData = new Float32Array(this.arrayBuffer);
            if (this._dataView) {
                newData.set(this._dataView);
            }
            this._dataView = newData;
            this._needResetData = true;
        }
        _upload() {
            if (this._needResetData) {
                let view = this._first;
                while (view) {
                    view._updateView(this._dataView);
                    view = view._next;
                }
                this.buffer.setData(this.arrayBuffer, 0, 0, this.arrayBuffer.byteLength);
                this._needResetData = false;
            }
            else {
                if (this._updateRange.y <= this._updateRange.x)
                    return;
                this.buffer.setData(this.arrayBuffer, this._updateRange.x * 4, this._updateRange.x * 4, (this._updateRange.y - this._updateRange.x) * 4);
            }
            this._updateRange.setValue(100000000, -100000000);
        }
    }
    class Web2DGraphicsIndexBuffer extends Web2DGraphicWholeBuffer {
        resetData(byteLength) {
            this.arrayBuffer = new ArrayBuffer(byteLength);
            let newData = new Uint16Array(this.arrayBuffer);
            if (this._dataView) {
                newData.set(this._dataView);
            }
            this._dataView = newData;
            this._needResetData = true;
        }
        _upload() {
            if (!this._num)
                return;
            let view = this._first;
            let start = 0;
            let length = 0;
            let geometry = view._geometry;
            let needUpdate = false;
            let uploadStart = this._needResetData ? 0 : this._updateRange.x;
            while (view) {
                if (geometry != view._geometry) {
                    if (needUpdate) {
                        geometry.clearRenderParams();
                        geometry.setDrawElemenParams(length, start * 2);
                    }
                    geometry = view._geometry;
                    start = start + length;
                    length = 0;
                }
                start = start + length;
                needUpdate = this._needResetData || start >= uploadStart;
                if (needUpdate) {
                    view.start = start;
                    view._updateView(this._dataView);
                }
                length += view.length;
                view = view._next;
            }
            if (needUpdate) {
                geometry.clearRenderParams();
                geometry.setDrawElemenParams(length, start * 2);
            }
            let len = this._last.start + this._last.length - uploadStart;
            let offset = uploadStart * 2;
            offset = Math.floor(offset / 4) * 4;
            this.buffer.setData(this.arrayBuffer, offset, offset, len * 2 + (uploadStart * 2 - offset));
            this._needResetData = false;
        }
        _modifyOneView(view) {
            if (view._prev) {
                view.start = view._prev.start + view._prev.length;
            }
            else {
                view.start = 0;
            }
            super._modifyOneView(view);
        }
    }
    class Web2DGraphicsIndexBatchBuffer extends Web2DGraphicsIndexBuffer {
        _upload() {
            let view = this._first;
            let uploadStart = this._needResetData ? 0 : this._updateRange.x;
            while (view) {
                if (this._needResetData || view.start >= uploadStart) {
                    view._updateView(this._dataView);
                }
                view = view._next;
            }
            let len = this._last.start + this._last.length - uploadStart;
            if (len == 0)
                return;
            let offset = uploadStart * 2;
            offset = Math.floor(offset / 4) * 4;
            let dataLength = len * 2 + (uploadStart * 2 - offset);
            if (dataLength + offset > this.arrayBuffer.byteLength) {
                offset -= (dataLength + offset - this.arrayBuffer.byteLength);
            }
            this.buffer.setData(this.arrayBuffer, offset, offset, dataLength);
            this._needResetData = false;
        }
        _modifyOneView(view) {
            this.addDataView(view);
            super._modifyOneView(view);
            if (view._geometry) {
                view._geometry.clearRenderParams();
                view._geometry.setDrawElemenParams(view.length, view.start * 2);
            }
        }
        clearBufferViews() {
            this._first = null;
            this._last = null;
            this._num = 0;
            this._updateRange.setValue(100000000, -100000000);
        }
        _resetData(byteLength) {
            super.resetData(byteLength);
        }
    }

    class BatchBuffer {
        constructor() {
            this.indexCount = 0;
            this.maxIndexCount = 0;
            this.bufferStates = new Map();
            this.indexBuffer = Laya.LayaGL.renderDeviceFactory.createIndexBuffer(Laya.BufferUsage.Dynamic);
            this.indexBuffer.indexType = Laya.IndexFormat.UInt16;
            this.wholeBuffer = new Web2DGraphicsIndexBatchBuffer();
            this.wholeBuffer.buffer = this.indexBuffer;
            if (!!Laya.LayaGL.renderEngine.gl) {
                this.add = this._addWebgl;
            }
            else {
                this.add = this._addWebgpu;
            }
        }
        _addWebgl(element) {
            let handle = element.owner.renderDataHandler;
            let blocks = handle._getBlocks();
            if (!blocks)
                return null;
            let cview = handle.getCloneViews()[element._index];
            let block = blocks[element._index];
            let vertexBuffer = block.vertexBuffer;
            let bufferState = this.bindBuffer(vertexBuffer);
            this.indexCount += cview.length;
            this.wholeBuffer._modifyOneView(cview);
            if (cview._geometry.bufferState !== bufferState) {
                cview._geometry.bufferState = bufferState;
            }
            WebRender2DPass.setBuffer(this.wholeBuffer);
            this.updateBufLength();
            return cview._geometry;
        }
        _addWebgpu(element) {
            let handle = element.owner.renderDataHandler;
            let blocks = handle._getBlocks();
            if (!blocks)
                return null;
            let cview = handle.getCloneViews()[element._index];
            let block = blocks[element._index];
            let vertexBuffer = block.vertexBuffer;
            let bufferState = this.bindBuffer(vertexBuffer);
            this.indexCount += cview.length;
            this.wholeBuffer._modifyOneView(cview);
            if (cview._geometry._bufferState !== bufferState) {
                cview._geometry.bufferState = bufferState;
            }
            WebRender2DPass.setBuffer(this.wholeBuffer);
            this.updateBufLength();
            return cview._geometry;
        }
        add(element) {
            return null;
        }
        updateBufLength() {
            if (this.maxIndexCount <= this.indexCount) {
                let nLength = Math.ceil(this.indexCount / _STEP_) * _STEP_;
                let byteLength = nLength * 2;
                this.indexBuffer._setIndexDataLength(byteLength);
                this.wholeBuffer._resetData(byteLength);
                this.maxIndexCount = nLength;
            }
        }
        bindBuffer(buffer) {
            let bufferState = this.bufferStates.get(buffer);
            if (!bufferState) {
                bufferState = Laya.LayaGL.renderDeviceFactory.createBufferState();
                bufferState.applyState([buffer], this.indexBuffer);
                this.bufferStates.set(buffer, bufferState);
            }
            return bufferState;
        }
        clear() {
            this.indexCount = 0;
            this.wholeBuffer.clearBufferViews();
        }
        destroy() {
            this.clear();
            this.bufferStates.forEach((bufferState) => {
                bufferState.destroy();
            });
            this.bufferStates.clear();
            this.indexBuffer.destroy();
            this.indexBuffer = null;
            this.wholeBuffer.destroy();
            this.wholeBuffer = null;
        }
    }
    class BaseBatchContext {
        constructor() {
            this.textureId = 0;
            this.globalAlpha = 1;
            this.clipInfo = null;
            this.subShader = null;
            this.bufferState = null;
            this.primitiveShaderData = null;
            this.materialShaderData = null;
            this.typeKey = 0;
            this.textureKey = 0;
            this.globalRenderData = null;
            this.fillTexture = false;
        }
    }
    class WebGLBatchContext extends BaseBatchContext {
        setHead(element) {
            this.primitiveShaderData = element.primitiveShaderData;
            this.materialShaderData = element.materialShaderData;
            this.subShader = element.subShader;
            this.bufferState = element.geometry.bufferState;
            this.typeKey = element.typeKey;
            this.textureKey = element.textureKey;
            this.textureId = element.textureKey & (~((1 << Laya.ShaderDefines2D.SHADER_DEFINE_BITS) - 1));
            this.globalAlpha = element.owner.globalAlpha;
            this.clipInfo = element.owner.getClipInfo();
            this.globalRenderData = element.owner.globalRenderData;
            this.fillTexture = !!(element.typeKey & 64);
            this.texRange = this.primitiveShaderData.getVector(Laya.ShaderDefines2D.UNIFORM_TEXRANGE);
        }
        isCompatible(element) {
            if (this.typeKey & 32)
                return false;
            if (element.typeKey & 32) {
                return false;
            }
            if (this.typeKey !== element.typeKey) {
                return false;
            }
            let defineMask = (1 << Laya.ShaderDefines2D.SHADER_DEFINE_BITS) - 1;
            if ((this.textureKey & defineMask) !== (element.textureKey & defineMask)) {
                return false;
            }
            let elementTexId = element.textureKey & (~defineMask);
            if (elementTexId !== 0 && elementTexId !== this.textureId && this.textureId !== 0)
                return false;
            if (this.subShader !== element.subShader ||
                this.bufferState !== element.geometry.bufferState ||
                this.clipInfo !== element.owner.getClipInfo() ||
                element.owner.globalRenderData !== this.globalRenderData) {
                return false;
            }
            if ((this.typeKey & 16) !== 0 && element.materialShaderData !== this.materialShaderData) {
                return false;
            }
            if (this.fillTexture) {
                if (!element.primitiveShaderData.getVector(Laya.ShaderDefines2D.UNIFORM_TEXRANGE).equal(this.texRange))
                    return false;
            }
            if (this.textureId === 0 && elementTexId !== 0) {
                this.textureId = elementTexId;
                this.primitiveShaderData = element.primitiveShaderData;
                this.textureKey = element.textureKey;
            }
            return true;
        }
    }
    class WebGPUBatchContext extends BaseBatchContext {
        setHead(element) {
            this.primitiveShaderData = element._primitiveShaderData;
            this.materialShaderData = element._materialShaderData;
            this.subShader = element._subShader;
            this.bufferState = element.geometry._bufferState;
            this.typeKey = element.typeKey;
            this.textureKey = element.textureKey;
            this.textureId = element.textureKey & (~((1 << Laya.ShaderDefines2D.SHADER_DEFINE_BITS) - 1));
            this.globalAlpha = element.owner.globalAlpha;
            this.clipInfo = element.owner.getClipInfo();
            this.globalRenderData = element.owner.globalRenderData;
            this.fillTexture = !!(element.typeKey & 64);
            this.texRange = this.primitiveShaderData.getVector(Laya.ShaderDefines2D.UNIFORM_TEXRANGE);
        }
        isCompatible(element) {
            if (this.typeKey & 32)
                return false;
            if (element.typeKey & 32) {
                return false;
            }
            if (this.typeKey !== element.typeKey) {
                return false;
            }
            let defineMask = (1 << Laya.ShaderDefines2D.SHADER_DEFINE_BITS) - 1;
            if ((this.textureKey & defineMask) !== (element.textureKey & defineMask)) {
                return false;
            }
            let elementTexId = element.textureKey & (~defineMask);
            if (elementTexId !== 0 && elementTexId !== this.textureId && this.textureId !== 0)
                return false;
            if (this.subShader !== element.subShader ||
                this.bufferState !== element.geometry.bufferState ||
                this.clipInfo !== element.owner.getClipInfo() ||
                element.owner.globalRenderData !== this.globalRenderData) {
                return false;
            }
            if ((this.typeKey & 16) !== 0 && element._materialShaderData !== this.materialShaderData) {
                return false;
            }
            if (this.fillTexture) {
                let primitiveShaderData = element._primitiveShaderData;
                if (!primitiveShaderData.getVector(Laya.ShaderDefines2D.UNIFORM_TEXRANGE).equal(this.texRange))
                    return false;
            }
            if (this.textureId === 0 && elementTexId !== 0) {
                this.textureId = elementTexId;
                this.primitiveShaderData = element._primitiveShaderData;
                this.textureKey = element.textureKey;
            }
            return true;
        }
    }
    class WebGraphicsBatch {
        constructor() {
            this._buffer = new BatchBuffer();
            this._merged = [];
            let isWebgl = !!Laya.LayaGL.renderEngine.gl;
            if (isWebgl) {
                this._context = new WebGLBatchContext();
            }
            else {
                this._context = new WebGPUBatchContext();
            }
        }
        reset() {
            this._buffer.clear();
            WebGraphicsBatch._pool.recover(this._merged);
        }
        destroy() {
            this._buffer.destroy();
            WebGraphicsBatch._pool.recover(this._merged);
        }
        batch(list, start, end, allowReorder) {
            let elementArray = list.elements;
            let ctx = this._context;
            ctx.setHead(elementArray[start]);
            let cnt = end - start + 1;
            if (cnt > 1000)
                allowReorder = false;
            if (allowReorder) {
                if (elementFlags == null)
                    initCache(1000);
                let headGroup = 0;
                let maxGroup = 1;
                let indiceLen = 1;
                elementIndice[0] = start;
                elementFlags[0] = 0;
                for (let i = 1; i < cnt; i++) {
                    let element = elementArray[start + i];
                    elementFlags[i] = -1;
                    let rect = element.owner.rect;
                    rectLeftCache[i] = rect.x;
                    rectTopCache[i] = rect.y;
                    rectRightCache[i] = rect.x + rect.width;
                    rectBottomCache[i] = rect.y + rect.height;
                }
                for (let i = 1; i < cnt; i++) {
                    let element = elementArray[start + i];
                    let group = elementFlags[i];
                    if (group === -2) {
                        continue;
                    }
                    if (group !== -1) {
                        if (group === headGroup) {
                            elementIndice[indiceLen++] = start + i;
                            continue;
                        }
                    }
                    else {
                        if (ctx.isCompatible(element)) {
                            elementIndice[indiceLen++] = start + i;
                            continue;
                        }
                        elementFlags[i] = group = maxGroup++;
                    }
                    for (let j = i + 1; j < cnt; j++) {
                        let element2 = elementArray[start + j];
                        if (elementFlags[j] !== -1) {
                            if (elementFlags[j] !== headGroup)
                                continue;
                        }
                        else {
                            if (!ctx.isCompatible(element2))
                                continue;
                        }
                        for (let k = j - 1; k >= i; k--) {
                            if (elementFlags[k] !== -2
                                && rectLeftCache[j] < rectRightCache[k] && rectRightCache[j] > rectLeftCache[k]
                                && rectTopCache[j] < rectBottomCache[k] && rectBottomCache[j] > rectTopCache[k]) {
                                element2 = null;
                                break;
                            }
                        }
                        if (element2 != null) {
                            elementIndice[indiceLen++] = start + j;
                            elementFlags[j] = -2;
                        }
                        else if (ctx.textureId !== 0)
                            elementFlags[j] = headGroup;
                    }
                    list.add(this.merge(elementArray, 0, indiceLen - 1, ctx, elementIndice));
                    indiceLen = 1;
                    elementIndice[0] = start + i;
                    headGroup = group;
                    ctx.setHead(element);
                }
                list.add(this.merge(elementArray, 0, indiceLen - 1, ctx, elementIndice));
            }
            else {
                let batchStart = start;
                for (let i = start + 1; i <= end; i++) {
                    let element = elementArray[i];
                    if (!ctx.isCompatible(element)) {
                        list.add(this.merge(elementArray, batchStart, i - 1, ctx));
                        batchStart = i;
                        ctx.setHead(element);
                    }
                }
                list.add(this.merge(elementArray, batchStart, end, ctx));
            }
        }
        merge(elementArray, start, end, batchContext, indice) {
            if (start === end) {
                let element = elementArray[indice !== undefined ? indice[start] : start];
                this._buffer.add(element);
                return element;
            }
            let staticBatchRenderElement = WebGraphicsBatch._pool.take();
            this._merged.push(staticBatchRenderElement);
            let batchedGeometry = staticBatchRenderElement.geometry;
            let currentOffset = 0;
            let currentCount = 0;
            let isFirst = true;
            for (let i = start; i <= end; i++) {
                let element = elementArray[indice !== undefined ? indice[i] : i];
                let geometry = this._buffer.add(element) || element.geometry;
                if (i === start) {
                    batchedGeometry.bufferState = geometry.bufferState;
                    staticBatchRenderElement.materialShaderData = element.materialShaderData;
                    staticBatchRenderElement.value2DShaderData = element.value2DShaderData;
                    staticBatchRenderElement.subShader = element.subShader;
                    staticBatchRenderElement.renderStateIsBySprite = element.renderStateIsBySprite;
                    staticBatchRenderElement.primitiveShaderData = batchContext.primitiveShaderData;
                    staticBatchRenderElement.owner = element.owner;
                    staticBatchRenderElement.typeKey = batchContext.typeKey;
                    staticBatchRenderElement.textureKey = batchContext.textureKey;
                }
                let drawParam = geometry.drawParams.elements;
                let drawLength = geometry.drawParams.length;
                for (let j = 0; j < drawLength; j += 2) {
                    let offset = drawParam[j];
                    let count = drawParam[j + 1];
                    if (isFirst) {
                        currentOffset = offset;
                        currentCount = count;
                        isFirst = false;
                        continue;
                    }
                    if (currentOffset + currentCount * 2 === offset) {
                        currentCount += count;
                    }
                    else {
                        batchedGeometry.setDrawElemenParams(currentCount, currentOffset);
                        currentOffset = offset;
                        currentCount = count;
                    }
                }
            }
            if (!isFirst) {
                batchedGeometry.setDrawElemenParams(currentCount, currentOffset);
            }
            return staticBatchRenderElement;
        }
    }
    WebGraphicsBatch._pool = Laya.Pool.createPool2(() => {
        let element = Laya.LayaGL.render2DRenderPassFactory.createPrimitiveRenderElement2D();
        element.geometry = Laya.LayaGL.renderDeviceFactory.createRenderGeometryElement(Laya.MeshTopology.Triangles, Laya.DrawType.DrawElement);
        element.geometry.indexFormat = Laya.IndexFormat.UInt16;
        element.nodeCommonMap = ["Sprite2D"];
        element.renderStateIsBySprite = false;
        return element;
    }, null, element => {
        element.geometry.clearRenderParams();
        element.geometry.bufferState = null;
        element.materialShaderData = null;
        element.value2DShaderData = null;
        element.primitiveShaderData = null;
        element.subShader = null;
        element.owner = null;
        element.renderStateIsBySprite = false;
        element.globalShaderData = null;
        element.typeKey = 0;
        element.textureKey = 0;
    });
    const _STEP_ = 1024;
    var elementFlags;
    var elementIndice;
    var rectLeftCache;
    var rectTopCache;
    var rectRightCache;
    var rectBottomCache;
    function initCache(maxElements) {
        elementFlags = new Int16Array(maxElements);
        elementIndice = new Int16Array(maxElements);
        rectLeftCache = new Float32Array(maxElements);
        rectTopCache = new Float32Array(maxElements);
        rectRightCache = new Float32Array(maxElements);
        rectBottomCache = new Float32Array(maxElements);
    }

    BatchManager.registerProvider(Laya.BaseRender2DType.graphics, WebGraphicsBatch);
    class SortedStructs {
        constructor() {
            this.lists = new Map();
            this._indice = new Set;
            this._sortedIndice = [];
        }
        add(struct, zIndex) {
            let list = this.lists.get(zIndex);
            if (!list)
                this.lists.set(zIndex, list = new Laya.FastSinglelist());
            list.add(struct);
            if (list.length === 1)
                this._indice.add(zIndex);
            return list;
        }
        reset() {
            this._indice.forEach(i => this.lists.get(i).length = 0);
            this._indice.clear();
            this._sortedIndice.length = 0;
        }
        get indice() {
            let arr = this._sortedIndice;
            if (arr.length === 0) {
                for (let zIndex of this._indice) {
                    arr.push(zIndex);
                }
                arr.sort((a, b) => a - b);
            }
            return arr;
        }
        appendTo(out) {
            this.indice.forEach(zIndex => out.addList(this.lists.get(zIndex)));
        }
    }
    class WebRender2DPass {
        get priority() {
            return this._priority;
        }
        set priority(value) {
            this._priority = value;
            if (this._mask)
                this._mask.setMaskParentPass(this);
        }
        get mask() {
            return this._mask;
        }
        set mask(value) {
            if (this._mask)
                this._mask.setMaskParentPass(null);
            this._mask = value;
            if (value)
                value.setMaskParentPass(this);
        }
        get enableBatch() {
            return this._enableBatch;
        }
        set enableBatch(value) {
            this.repaint = true;
            this._enableBatch = value;
        }
        setClearColor(r, g, b, a) {
            this._clearColor.setValue(r, g, b, a);
        }
        constructor() {
            this._renderElements = new Laya.FastSinglelist();
            this._elementGroups = new Laya.FastSinglelist();
            this._structs = new SortedStructs();
            this._structsPool = Laya.Pool.createPool(SortedStructs, null, obj => obj.reset());
            this._batchProviders = [];
            this._priority = 0;
            this.enable = true;
            this.isSupport = false;
            this.postProcess = null;
            this.repaint = true;
            this._clearColor = new Laya.Color;
            this.doClearColor = true;
            this.finalize = null;
            this._enableBatch = true;
            this._rtsize = new Laya.Vector2;
            this.root = null;
            this.offsetMatrix = new Laya.Matrix();
            this._invertMat_0 = new Laya.Vector3(1, 1);
            this._invertMat_1 = new Laya.Vector3(0, 0);
            this.shaderData = null;
            this.destroyed = false;
            this.shaderData = Laya.LayaGL.renderDeviceFactory.createShaderData(null);
        }
        needRender() {
            return this.enable
                && !this.isSupport
                && (this.repaint || !this.renderTexture);
        }
        cullAndSort(context2D, struct) {
            if (!struct.enabled
                || struct.globalAlpha < 0.01
                || this._mask === struct)
                return;
            let renderStruct = (struct.subStruct && struct !== this.root) ? struct.subStruct : struct;
            renderStruct._handleInterData();
            let globalRenderData = struct.globalRenderData;
            if (globalRenderData) {
                if (struct._currentData.globalRenderData
                    && (struct.renderLayer & globalRenderData.renderLayerMask) === 0) {
                    return;
                }
                let cullRect = globalRenderData.cullRect;
                if (struct.inheritedEnableCulling && cullRect && !this._isRectIntersect(struct.rect, cullRect)) {
                    return;
                }
            }
            renderStruct.renderUpdate(context2D);
            let list = this._pStructs.add(renderStruct, struct._effectZ);
            if (struct.stackingRoot) {
                var oldCol = this._pStructs;
                this._pStructs = this._structsPool.take();
            }
            for (let i = 0, n = renderStruct.children.length; i < n; i++) {
                const child = renderStruct.children[i];
                child._effectZ = child.zIndex + struct._effectZ;
                this.cullAndSort(context2D, child);
            }
            if (oldCol) {
                this._pStructs.appendTo(list);
                this._structsPool.recover(this._pStructs);
                this._pStructs = oldCol;
            }
            if (struct.dcOptimize) {
                let last = list.length - 1;
                struct.dcOptimizeEnd = list.elements[last];
            }
        }
        _isRectIntersect(rect, cullRect) {
            let rect_minx = rect.x;
            let rect_maxx = rect.x + rect.width;
            let rect_miny = rect.y;
            let rect_maxy = rect.y + rect.height;
            return !(rect_maxx < cullRect.x || rect_minx > cullRect.y || rect_maxy < cullRect.z || rect_miny > cullRect.w);
        }
        fowardRender(context, renderTime) {
            var _a, _b;
            let success = this._initRenderProcess(context, renderTime);
            if (!success)
                return;
            if (this.repaint) {
                this._structs.reset();
                this._renderElements.length = 0;
                for (let i = 0, n = this._batchProviders.length; i < n; i++) {
                    (_a = this._batchProviders[i]) === null || _a === void 0 ? void 0 : _a.reset();
                }
                if (this.root) {
                    this._pStructs = this._structs;
                    this.cullAndSort(context, this.root);
                    this.fillRenderElements();
                    this._enableBatch && Laya.LayaEnv.isPlaying && this.batch();
                }
                WebRender2DPass.uploadBuffer();
                context.drawRenderElementList(this._renderElements);
                if (this._mask) {
                    let renderMask = this._mask.subStruct;
                    renderMask._handleInterData();
                    renderMask.renderUpdate(context);
                    context.drawRenderElementOne(renderMask.renderElements[0]);
                }
                if ((_b = this.postProcess) === null || _b === void 0 ? void 0 : _b.enabled) {
                    this.postProcess.apply();
                }
            }
            else {
                this._structs.indice.forEach(index => {
                    let list = this._structs.lists.get(index);
                    for (let i = 0, cnt = list.length; i < cnt; i++) {
                        let struct = list.elements[i];
                        struct._handleInterData();
                        struct.renderUpdate(context);
                    }
                });
                WebRender2DPass.uploadBuffer();
                context.drawRenderElementList(this._renderElements);
            }
            this.repaint = false;
        }
        fillRenderElements() {
            this._elementGroups.length = 0;
            let groupStart = 0;
            let reorderRoot;
            let renderElements = this._renderElements;
            this._structs.indice.forEach(index => {
                let list = this._structs.lists.get(index);
                for (let i = 0, cnt = list.length; i < cnt; i++) {
                    let struct = list.elements[i];
                    let n = struct.renderElements ? struct.renderElements.length : 0;
                    if (struct.owner._getBit(Laya.NodeFlags.HIDE_BY_EDITOR))
                        n = 0;
                    if (struct.dcOptimize && !reorderRoot && struct.dcOptimizeEnd !== struct) {
                        reorderRoot = struct;
                        if (groupStart !== renderElements.length) {
                            this._elementGroups.add(groupStart);
                            this._elementGroups.add(renderElements.length - 1);
                            this._elementGroups.add(false);
                            groupStart = renderElements.length;
                        }
                    }
                    if (n > 0) {
                        for (let i = 0; i < n; i++) {
                            let element = struct.renderElements[i];
                            element._index = i;
                            element.geometry && renderElements.add(element);
                        }
                    }
                    if ((reorderRoot === null || reorderRoot === void 0 ? void 0 : reorderRoot.dcOptimizeEnd) === struct) {
                        reorderRoot = null;
                        if (groupStart !== renderElements.length) {
                            this._elementGroups.add(groupStart);
                            this._elementGroups.add(renderElements.length - 1);
                            this._elementGroups.add(true);
                            groupStart = renderElements.length;
                        }
                    }
                }
            });
            if (groupStart !== renderElements.length) {
                this._elementGroups.add(groupStart);
                this._elementGroups.add(renderElements.length - 1);
                this._elementGroups.add(false);
            }
        }
        batch() {
            let list = this._renderElements;
            let elementArray = list.elements;
            let groups = this._elementGroups;
            let groupsArray = groups.elements;
            list.length = 0;
            for (let gi = 0, gl = groups.length; gi < gl; gi += 3) {
                let groupStart = groupsArray[gi];
                let groupEnd = groupsArray[gi + 1];
                let allowReorder = groupsArray[gi + 2];
                let lastRenderType = elementArray[groupStart].owner.renderType;
                let batchStart = groupStart;
                for (let i = groupStart + 1; i <= groupEnd; i++) {
                    let element = elementArray[i];
                    let struct = element.owner;
                    if (lastRenderType === struct.renderType)
                        continue;
                    if (i - batchStart > 1)
                        this.getBatchProvider(lastRenderType).batch(list, batchStart, i - 1, allowReorder);
                    else
                        list.add(elementArray[batchStart]);
                    batchStart = i;
                    lastRenderType = struct.renderType;
                }
                if (groupEnd - batchStart > 0)
                    this.getBatchProvider(lastRenderType).batch(list, batchStart, groupEnd, allowReorder);
                else
                    list.add(elementArray[batchStart]);
            }
        }
        getBatchProvider(renderType) {
            return this._batchProviders[renderType] || (this._batchProviders[renderType] = BatchManager.createProvider(renderType));
        }
        _initRenderProcess(context, renderTime) {
            if (!this.root || this.root.globalAlpha < 0.01) {
                return false;
            }
            let sizeX, sizeY;
            let rt = this.renderTexture;
            if (rt) {
                if (rt.width == 0 || rt.height == 0)
                    return false;
                context.invertY = rt._invertY;
                context.setRenderTarget(rt._renderTarget, this.doClearColor, this._clearColor);
                sizeX = rt.width;
                sizeY = rt.height;
                let result = this._updateInvertMatrix();
                if (!result) {
                    return false;
                }
                this.shaderData.addDefine(Laya.ShaderDefines2D.RENDERTEXTURE);
            }
            else {
                sizeX = Laya.RenderState2D.width;
                sizeY = Laya.RenderState2D.height;
                if (sizeX === 0 || sizeY === 0)
                    return false;
                context.invertY = false;
                context.setOffscreenView(sizeX, sizeY, 0, 0);
                context.setRenderTarget(null, this.doClearColor, this._clearColor);
                this._setInvertMatrix(1, 0, 0, 1, 0, 0);
                this.shaderData.removeDefine(Laya.ShaderDefines2D.RENDERTEXTURE);
            }
            context.passData = this.shaderData;
            if (sizeX !== this._rtsize.x || sizeY !== this._rtsize.y) {
                this._rtsize.setValue(sizeX, sizeY);
                this.shaderData.setVector2(Laya.ShaderDefines2D.UNIFORM_SIZE, this._rtsize);
            }
            this.shaderData.setNumber(Laya.ShaderDefines2D.UNIFORM_TIME, renderTime);
            return true;
        }
        static setBuffer(buffer) {
            if (buffer._inPass)
                return;
            buffer._inPass = true;
            WebRender2DPass.buffers.add(buffer);
        }
        static uploadBuffer() {
            if (WebRender2DPass.buffers.length > 0) {
                let elements = WebRender2DPass.buffers.elements;
                for (let i = 0, n = WebRender2DPass.buffers.length; i < n; i++) {
                    let buffer = elements[i];
                    buffer._upload();
                    buffer._inPass = false;
                }
                WebRender2DPass.buffers.length = 0;
            }
        }
        _updateInvertMatrix() {
            let rootTrans = this.root.trans;
            if (!rootTrans) {
                this._setInvertMatrix(1, 0, 0, 1, 0, 0);
                return true;
            }
            if (rootTrans.matrix.a == 0
                && rootTrans.matrix.b == 0
                && rootTrans.matrix.c == 0
                && rootTrans.matrix.d == 0) {
                return false;
            }
            let temp = _TEMP_InvertMatrix;
            let mask = this.mask;
            let offset = this.offsetMatrix;
            if (mask && mask.trans) {
                let maskMatrix = mask.renderMatrix;
                maskMatrix.copyTo(temp);
            }
            else {
                rootTrans.matrix.copyTo(temp);
            }
            Laya.Matrix.mul(offset, temp, temp);
            temp.invert();
            this._setInvertMatrix(temp.a, temp.b, temp.c, temp.d, temp.tx, temp.ty);
            return true;
        }
        _setInvertMatrix(a = 1, b = 0, c = 0, d = 1, tx = 0, ty = 0) {
            if (a === this._invertMat_0.x
                && b === this._invertMat_1.x
                && c === this._invertMat_0.y
                && d === this._invertMat_1.y
                && tx === this._invertMat_0.z
                && ty === this._invertMat_1.z)
                return;
            this._invertMat_0.setValue(a, c, tx);
            this._invertMat_1.setValue(b, d, ty);
            this.shaderData.setVector3(Laya.ShaderDefines2D.UNIFORM_INVERTMAT_0, this._invertMat_0);
            this.shaderData.setVector3(Laya.ShaderDefines2D.UNIFORM_INVERTMAT_1, this._invertMat_1);
        }
        updatePostProcess() { }
        destroy() {
            if (this.destroyed) {
                return;
            }
            this.destroyed = true;
            this._renderElements.length = 0;
            for (let i = 0, n = this._batchProviders.length; i < n; i++) {
                this._batchProviders[i] && this._batchProviders[i].destroy();
            }
            this._batchProviders.length = 0;
            this.root = null;
            this.renderTexture = null;
            this.postProcess = null;
            this.shaderData.destroy();
            this.shaderData = null;
        }
    }
    WebRender2DPass.buffers = new Laya.FastSinglelist();
    class WebRender2DPassManager {
        constructor() {
            this._modify = false;
            this._passes = [];
        }
        removePass(pass) {
            let index = this._passes.indexOf(pass);
            if (index === -1) {
                return;
            }
            this._passes.splice(index, 1);
            this._modify = true;
        }
        apply(context, renderTime) {
            if (this._modify) {
                this._modify = false;
                this._passes.sort((a, b) => b._priority - a._priority);
            }
            for (const pass of this._passes) {
                if (pass.needRender()) {
                    pass.fowardRender(context, renderTime);
                }
            }
        }
        clear() {
            this._passes.length = 0;
        }
        addPass(pass) {
            if (this._passes.indexOf(pass) !== -1) {
                return;
            }
            this._passes.push(pass);
            this._modify = true;
        }
    }
    const _TEMP_InvertMatrix = new Laya.Matrix();

    class Web2DGraphicsBufferDataView {
    }
    class Web2DGraphic2DVertexDataView extends Web2DGraphicsBufferDataView {
        _getData() {
            return this._view;
        }
        _modify() {
            this.owner._modifyOneView(this);
            WebRender2DPass.setBuffer(this.owner);
        }
        _updateView(wholeData) {
            if (!this._view || this._view.buffer !== wholeData.buffer) {
                this._view = new Float32Array(wholeData.buffer, this.start * 4, this.length);
            }
        }
        setData(data) {
            this._view.set(data);
            this._modify();
        }
        constructor(owner, start, length, stride = 1) {
            super();
            this.stride = 1;
            this.owner = owner;
            this.start = start;
            this.length = length;
            this.stride = stride;
            this._updateView(owner._dataView);
            owner.addDataView(this);
        }
    }
    class Web2DGraphic2DIndexDataView extends Web2DGraphicsBufferDataView {
        setGeometry(value) {
            this._geometry = value;
        }
        setData(data) {
            this._view.set(data);
            this._modify();
        }
        constructor(owner, length, create = true) {
            super();
            this.owner = owner;
            this.length = length;
            if (create) {
                this._view = new Uint16Array(length);
            }
        }
        _updateView(wholeData) {
            wholeData.set(this._view, this.start);
        }
        _modify() {
            this.owner._modifyOneView(this);
            WebRender2DPass.setBuffer(this.owner);
        }
        _clone(cloneOwner = true, create = true) {
            let owner = cloneOwner ? this.owner : null;
            let nview = new Web2DGraphic2DIndexCloneDataView(owner, this.length, create);
            if (!create) {
                this._cloneView(nview);
            }
            return nview;
        }
        _cloneView(view) {
            view._view = this._view;
            view.length = this.length;
        }
        destroy() {
            this._view = null;
            this._geometry = null;
            this.owner = null;
            this._next = null;
            this._prev = null;
        }
    }
    class Web2DGraphic2DIndexCloneDataView extends Web2DGraphic2DIndexDataView {
        destroy() {
            super.destroy();
        }
    }

    class WebRender2DDataHandle {
        get owner() {
            return this._owner;
        }
        set owner(value) {
            this._owner = value;
        }
        constructor() {
            this._nMatrix_0 = new Laya.Vector3();
            this._nMatrix_1 = new Laya.Vector3();
            this._needUseMatrix = true;
        }
        get needUseMatrix() {
            return this._needUseMatrix;
        }
        set needUseMatrix(value) {
            this._needUseMatrix = value;
            if (!value) {
                this._nMatrix_0.set(1, 0, 0);
                this._nMatrix_1.set(0, 1, 0);
                this._owner.spriteShaderData.setVector3(Laya.ShaderDefines2D.UNIFORM_NMATRIX_0, this._nMatrix_0);
                this._owner.spriteShaderData.setVector3(Laya.ShaderDefines2D.UNIFORM_NMATRIX_1, this._nMatrix_1);
            }
        }
        destroy() {
        }
        inheriteRenderData(context) {
            let data = this._owner.spriteShaderData;
            if (!data)
                return;
            if (this._needUseMatrix) {
                let mat = this._owner.renderMatrix;
                this._nMatrix_0.setValue(mat.a, mat.c, mat.tx);
                this._nMatrix_1.setValue(mat.b, mat.d, mat.ty);
                this._owner.spriteShaderData.setVector3(Laya.ShaderDefines2D.UNIFORM_NMATRIX_0, this._nMatrix_0);
                this._owner.spriteShaderData.setVector3(Laya.ShaderDefines2D.UNIFORM_NMATRIX_1, this._nMatrix_1);
            }
        }
    }
    class WebEmptyRender2DDataHandle extends WebRender2DDataHandle {
        inheriteRenderData(_context) {
        }
        destroy() {
        }
    }
    class WebGraphics2DBufferBlock {
    }
    class WebGraphics2DVertexBlock {
    }
    class WebPrimitiveDataHandle extends WebRender2DDataHandle {
        constructor() {
            super(...arguments);
            this.logicMatrix = null;
            this.mask = null;
            this._bufferBlocks = null;
            this._modifiedFrame = -1;
            this._globalAlpha = 1;
        }
        applyVertexBufferBlock(blocks) {
            this._bufferBlocks = blocks;
            this.updateCloneView();
            this._globalAlpha = this._owner.globalAlpha;
            if (this._owner.trans) {
                this._modifiedFrame = this._owner.trans.modifiedFrame;
            }
        }
        skipBufferUpdate() {
            if (this._owner.trans) {
                this._modifiedFrame = this._owner.trans.modifiedFrame;
            }
        }
        _getBlocks() {
            return this._bufferBlocks;
        }
        inheriteRenderData(context) {
            let data = this._owner.spriteShaderData;
            if (!data)
                return;
            let trans = this._owner.trans;
            let mat = trans.matrix;
            if (this._modifiedFrame < trans.modifiedFrame) {
                if (!this._bufferBlocks || !this._bufferBlocks.length) {
                    if (this.logicMatrix) {
                        let temp = Laya.Matrix.TEMP;
                        Laya.Matrix.mul(this.logicMatrix, mat.copyTo(temp), temp);
                        this._nMatrix_0.setValue(temp.a, temp.c, temp.tx);
                        this._nMatrix_1.setValue(temp.b, temp.d, temp.ty);
                    }
                    else {
                        this._nMatrix_0.setValue(mat.a, mat.c, mat.tx);
                        this._nMatrix_1.setValue(mat.b, mat.d, mat.ty);
                    }
                    this._owner.spriteShaderData.setVector3(Laya.ShaderDefines2D.UNIFORM_NMATRIX_0, this._nMatrix_0);
                    this._owner.spriteShaderData.setVector3(Laya.ShaderDefines2D.UNIFORM_NMATRIX_1, this._nMatrix_1);
                }
                else {
                    this._updateVertexData(mat, this._owner.globalAlpha, true, true, false);
                    this._globalAlpha = this._owner.globalAlpha;
                }
                this._modifiedFrame = trans.modifiedFrame;
            }
            else if (this._globalAlpha != this._owner.globalAlpha) {
                this._globalAlpha = this._owner.globalAlpha;
                if (this._bufferBlocks && this._bufferBlocks.length)
                    this._updateVertexData(mat, this._owner.globalAlpha, false, true, false);
            }
        }
        _updateVertexData(mat, globalAlpha, updateMatrix, updateGlobalAlpha, updateTextureArrayLayerIndex) {
            let pos = 0, dataViewIndex = 0, ci = 0;
            let dataView = null;
            let m00 = 1, m01 = 0, m10 = 0, m11 = 1, tx = 0, ty = 0;
            if (updateMatrix) {
                m00 = mat.a, m01 = mat.b, m10 = mat.c, m11 = mat.d, tx = mat.tx, ty = mat.ty;
            }
            let vbdata = null;
            let vertexCount = 0, positions = null, vertexViews = null;
            let stride = this._bufferBlocks[0].vertexBuffer.vertexDeclaration.vertexStride / 4;
            let textureArrayLayerIndex = 0;
            for (let i = 0, n = this._bufferBlocks.length; i < n; i++) {
                let vertexs = this._bufferBlocks[i].vertexs;
                textureArrayLayerIndex = this._bufferBlocks[i].textureArrayIndex;
                for (let index = 0, len = vertexs.length; index < len; index++) {
                    positions = vertexs[index].positions;
                    vertexViews = vertexs[index].vertexViews;
                    vertexCount = positions.length / 2;
                    dataView = null;
                    pos = 0, ci = 0, dataViewIndex = 0;
                    for (let j = 0; j < vertexCount; j++) {
                        if (!dataView || dataView.length <= pos) {
                            dataView = vertexViews[dataViewIndex];
                            dataView._modify();
                            dataViewIndex++;
                            pos = 0;
                            vbdata = dataView._getData();
                        }
                        if (updateMatrix) {
                            let x = positions[ci], y = positions[ci + 1];
                            vbdata[pos] = x * m00 + y * m10 + tx;
                            vbdata[pos + 1] = x * m01 + y * m11 + ty;
                        }
                        if (updateGlobalAlpha) {
                            vbdata[pos + 10] = globalAlpha;
                        }
                        if (updateTextureArrayLayerIndex) {
                            vbdata[pos + 11] = textureArrayLayerIndex;
                        }
                        pos += stride;
                        ci += 2;
                    }
                }
            }
        }
        getCloneViews() {
            if (!this._clonesViews) {
                this._clonesViews = [];
                for (let i = 0, n = this._bufferBlocks.length; i < n; i++) {
                    this._clonesViews[i] = this._cloneView(this._bufferBlocks[i].indexView);
                }
            }
            return this._clonesViews;
        }
        updateCloneView() {
            let cloneViews = this.getCloneViews();
            let blockLength = this._bufferBlocks.length;
            let cloneLength = cloneViews.length;
            if (cloneLength > blockLength) {
                for (let i = blockLength; i < cloneLength; i++) {
                    let view = cloneViews[i];
                    view._geometry.destroy();
                    if (view.owner)
                        view.owner.removeDataView(view);
                }
            }
            this._clonesViews.length = blockLength;
            for (let i = 0; i < blockLength; i++) {
                let view = cloneViews[i];
                let block = this._bufferBlocks[i];
                if (block) {
                    cloneViews[i] = this._cloneView(block.indexView, view);
                }
            }
        }
        _cloneView(view, oView = null) {
            let clone;
            if (oView && oView._geometry) {
                clone = oView;
                view._cloneView(clone);
            }
            else {
                clone = view._clone(false, false);
                clone._geometry = Laya.LayaGL.renderDeviceFactory.createRenderGeometryElement(Laya.MeshTopology.Triangles, Laya.DrawType.DrawElement);
                clone._geometry.indexFormat = Laya.IndexFormat.UInt16;
            }
            return clone;
        }
        destroy() {
            super.destroy();
            if (this._clonesViews) {
                for (let i = 0, n = this._clonesViews.length; i < n; i++)
                    this._clonesViews[i]._geometry.destroy();
                this._clonesViews = null;
            }
            this._bufferBlocks = null;
        }
    }
    class Web2DBaseRenderDataHandle extends WebRender2DDataHandle {
        constructor() {
            super(...arguments);
            this._lightReceive = false;
        }
        get lightReceive() {
            return this._lightReceive;
        }
        set lightReceive(value) {
            this._lightReceive = value;
            if (value) {
                this._owner.spriteShaderData.addDefine(Laya.BaseRenderNode2D.SHADERDEFINE_LIGHT2D_ENABLE);
            }
            else {
                this._owner.spriteShaderData.removeDefine(Laya.BaseRenderNode2D.SHADERDEFINE_LIGHT2D_ENABLE);
            }
        }
        get owner() {
            return this._owner;
        }
        set owner(value) {
            if (value == this.owner)
                return;
            if (this._owner) {
                this._owner.spriteShaderData.removeDefine(Laya.BaseRenderNode2D.SHADERDEFINE_BASERENDER2D);
            }
            this._owner = value;
            if (this._owner) {
                this._owner.spriteShaderData.addDefine(Laya.BaseRenderNode2D.SHADERDEFINE_BASERENDER2D);
            }
        }
    }
    const _setRenderColor = new Laya.Color(1, 1, 1, 1);
    class WebMesh2DRenderDataHandle extends Web2DBaseRenderDataHandle {
        constructor() {
            super(...arguments);
            this._baseColor = new Laya.Color(1, 1, 1, 1);
            this._tilingOffset = new Laya.Vector4();
            this._renderAlpha = -1;
        }
        get baseColor() {
            return this._baseColor;
        }
        set baseColor(value) {
            if (value != this._baseColor && this._baseColor.equal(value))
                return;
            value = value ? value : Laya.Color.BLACK;
            value.cloneTo(this._baseColor);
            this._renderAlpha = -1;
            this._owner.spriteShaderData.setColor(Laya.BaseRenderNode2D.BASERENDER2DCOLOR, this._baseColor);
        }
        get baseTexture() {
            return this._baseTexture;
        }
        set baseTexture(value) {
            if (this._baseTexture != null && value == this._baseTexture)
                return;
            if (this._baseTexture)
                this._baseTexture._removeReference();
            this._baseTexture = value;
            value = value ? value : Laya.Texture2D.whiteTexture;
            this._owner.spriteShaderData.setTexture(Laya.BaseRenderNode2D.BASERENDER2DTEXTURE, value);
            if (value) {
                value._addReference();
                if (value.gammaCorrection != 1) {
                    this._owner.spriteShaderData.addDefine(Laya.ShaderDefines2D.GAMMATEXTURE);
                }
                else {
                    this._owner.spriteShaderData.removeDefine(Laya.ShaderDefines2D.GAMMATEXTURE);
                }
            }
        }
        get tilingOffset() {
            return this._tilingOffset;
        }
        set tilingOffset(value) {
            if (!value)
                return;
            this._owner.spriteShaderData.setVector(Laya.BaseRenderNode2D.TILINGOFFSET, value);
            value ? value.cloneTo(this._tilingOffset) : null;
        }
        get normal2DTexture() {
            return this._normal2DTexture;
        }
        set normal2DTexture(value) {
            if (value === this._normal2DTexture)
                return;
            if (this._normal2DTexture)
                this._normal2DTexture._removeReference(1);
            if (value)
                value._addReference();
            this._normal2DTexture = value;
            this._owner.spriteShaderData.setTexture(Laya.BaseRenderNode2D.NORMAL2DTEXTURE, value);
            if (this._normal2DStrength > 0 && this._normal2DTexture)
                this._owner.spriteShaderData.addDefine(Laya.BaseRenderNode2D.SHADERDEFINE_LIGHT2D_NORMAL_PARAM);
            else
                this._owner.spriteShaderData.removeDefine(Laya.BaseRenderNode2D.SHADERDEFINE_LIGHT2D_NORMAL_PARAM);
        }
        get normal2DStrength() {
            return this._normal2DStrength;
        }
        set normal2DStrength(value) {
            value = Math.max(0, Math.min(1, value));
            if (this._normal2DStrength === value)
                return;
            this._normal2DStrength = value;
            this._owner.spriteShaderData.setNumber(Laya.BaseRenderNode2D.NORMAL2DSTRENGTH, value);
            if (value > 0 && this._normal2DTexture)
                this._owner.spriteShaderData.addDefine(Laya.BaseRenderNode2D.SHADERDEFINE_LIGHT2D_NORMAL_PARAM);
            else
                this._owner.spriteShaderData.removeDefine(Laya.BaseRenderNode2D.SHADERDEFINE_LIGHT2D_NORMAL_PARAM);
        }
        inheriteRenderData(context) {
            super.inheriteRenderData(context);
            if (this._renderAlpha != this._owner.globalAlpha) {
                let a = this._owner.globalAlpha * this._baseColor.a;
                _setRenderColor.setValue(this._baseColor.r, this._baseColor.g, this._baseColor.b, a);
                this._owner.spriteShaderData.setColor(Laya.BaseRenderNode2D.BASERENDER2DCOLOR, _setRenderColor);
                this._renderAlpha = this._owner.globalAlpha;
            }
        }
    }
    class WebSpineRenderDataHandle extends Web2DBaseRenderDataHandle {
        constructor() {
            super(...arguments);
            this._renderAlpha = -1;
            this._baseColor = new Laya.Color(1, 1, 1, 1);
            this.normalUpdater = null;
        }
        get baseColor() {
            return this._baseColor;
        }
        set baseColor(value) {
            if (value != this._baseColor && this._baseColor.equal(value))
                return;
            value = value ? value : Laya.Color.BLACK;
            value.cloneTo(this._baseColor);
            this._renderAlpha = -1;
            this._owner.spriteShaderData.setColor(Laya.BaseRenderNode2D.BASERENDER2DCOLOR, this._baseColor);
        }
        get owner() {
            return this._owner;
        }
        set owner(value) {
            if (value == this.owner)
                return;
            if (this._owner) {
                let shaderData = this._owner.spriteShaderData;
                shaderData.removeDefine(Laya.BaseRenderNode2D.SHADERDEFINE_BASERENDER2D);
                shaderData.removeDefine(Laya.SpineShaderInit.SPINE_UV);
                shaderData.removeDefine(Laya.SpineShaderInit.SPINE_COLOR);
            }
            this._owner = value;
            if (this._owner) {
                let shaderData = this._owner.spriteShaderData;
                shaderData.addDefine(Laya.BaseRenderNode2D.SHADERDEFINE_BASERENDER2D);
                shaderData.addDefine(Laya.SpineShaderInit.SPINE_UV);
                shaderData.addDefine(Laya.SpineShaderInit.SPINE_COLOR);
            }
        }
        get offset() {
            return this._offset;
        }
        set offset(value) {
            this._offset = value;
        }
        inheriteRenderData(context) {
            if (!this._owner || !this._owner.spriteShaderData || !this.skeleton)
                return;
            let shaderData = this.owner.spriteShaderData;
            let trans = this.owner.renderMatrix;
            let mat = trans;
            if (this._offset) {
                let ofx = this._offset.x;
                let ofy = this._offset.y;
                this._nMatrix_0.setValue(mat.a, mat.c, mat.tx + mat.a * ofx + mat.c * ofy);
                this._nMatrix_1.setValue(mat.b, mat.d, mat.ty + mat.b * ofx + mat.d * ofy);
            }
            else {
                this._nMatrix_0.setValue(mat.a, mat.c, mat.tx);
                this._nMatrix_1.setValue(mat.b, mat.d, mat.ty);
            }
            shaderData.setVector3(Laya.ShaderDefines2D.UNIFORM_NMATRIX_0, this._nMatrix_0);
            shaderData.setVector3(Laya.ShaderDefines2D.UNIFORM_NMATRIX_1, this._nMatrix_1);
            if (this._renderAlpha != this._owner.globalAlpha) {
                let a = this._owner.globalAlpha * this._baseColor.a;
                _setRenderColor.setValue(this._baseColor.r, this._baseColor.g, this._baseColor.b, a);
                this._owner.spriteShaderData.setColor(Laya.BaseRenderNode2D.BASERENDER2DCOLOR, _setRenderColor);
                this._renderAlpha = this._owner.globalAlpha;
            }
        }
    }

    const _DefaultClipInfo = {
        clipMatrix: new Laya.Matrix(),
        clipMatDir: new Laya.Vector4(Laya.Const.MAX_CLIP_SIZE, 0, 0, Laya.Const.MAX_CLIP_SIZE),
        clipMatPos: new Laya.Vector4(0, 0, 0, 0),
        _updateFrame: 0
    };
    class WebGlobalRenderData {
    }
    var ChildrenUpdateType;
    (function (ChildrenUpdateType) {
        ChildrenUpdateType[ChildrenUpdateType["All"] = -1] = "All";
        ChildrenUpdateType[ChildrenUpdateType["None"] = 0] = "None";
        ChildrenUpdateType[ChildrenUpdateType["Clip"] = 1] = "Clip";
        ChildrenUpdateType[ChildrenUpdateType["Blend"] = 2] = "Blend";
        ChildrenUpdateType[ChildrenUpdateType["Alpha"] = 4] = "Alpha";
        ChildrenUpdateType[ChildrenUpdateType["Pass"] = 8] = "Pass";
        ChildrenUpdateType[ChildrenUpdateType["Global"] = 16] = "Global";
        ChildrenUpdateType[ChildrenUpdateType["Culling"] = 32] = "Culling";
        ChildrenUpdateType[ChildrenUpdateType["DcOptimize"] = 64] = "DcOptimize";
    })(ChildrenUpdateType || (ChildrenUpdateType = {}));
    const _DefaultParentData = {
        clipInfo: _DefaultClipInfo,
        blendMode: Laya.BlendMode.invalid,
        globalRenderData: null,
        pass: null,
        enableCulling: false,
        dcOptimize: false,
        globalAlpha: 1,
    };
    class WebRenderStruct2D {
        get enableCulling() {
            return this._enableCulling;
        }
        set enableCulling(value) {
            this._enableCulling = value;
            this.updateChildren(ChildrenUpdateType.Culling);
        }
        get inheritedEnableCulling() {
            return this._enableCulling || this._parentData.enableCulling;
        }
        get dcOptimize() {
            return this._dcOptimize;
        }
        set dcOptimize(value) {
            this._dcOptimize = value;
            this.updateChildren(ChildrenUpdateType.DcOptimize);
        }
        get inheritedDcOptimize() {
            return this._dcOptimize || this._parentData.dcOptimize;
        }
        get renderMatrix() {
            return this.trans.matrix;
        }
        set renderMatrix(value) {
            if (this.trans) {
                this.trans.matrix = value;
                this.trans.modifiedFrame = Laya.Stat.loopCount;
            }
            else {
                this.trans = { matrix: value, modifiedFrame: Laya.Stat.loopCount };
            }
        }
        get globalAlpha() {
            return this._currentData.globalAlpha;
        }
        set globalAlpha(value) {
            this._parentData.globalAlpha = value;
        }
        get alpha() {
            return this._alpha;
        }
        set alpha(value) {
            this._alpha = value;
            this._updateGlobalAlpha(value, this.parent ? this.parent.globalAlpha : 1);
            this.updateChildren(ChildrenUpdateType.Alpha);
        }
        get blendMode() {
            return this._blendMode || this._currentData.blendMode || Laya.BlendMode.normal;
        }
        set blendMode(value) {
            this._updateBlendMode(value);
            this._setBlendMode();
            this.updateChildren(ChildrenUpdateType.Blend);
        }
        get renderDataHandler() {
            return this._renderDataHandler;
        }
        set renderDataHandler(value) {
            if (this._renderDataHandler) {
                this._renderDataHandler.owner = null;
            }
            this._renderDataHandler = value;
            if (value)
                this._renderDataHandler.owner = this;
        }
        get globalRenderData() {
            return this._globalRenderData || this._currentData.globalRenderData;
        }
        set globalRenderData(value) {
            this._globalRenderData = value;
            this._updateGlobalShaderData();
            this.updateChildren(ChildrenUpdateType.Global);
        }
        _updateGlobalShaderData() {
            let renderData = this.globalRenderData;
            if (renderData) {
                this._globalShaderData = renderData.globalShaderData;
            }
            else {
                this._globalShaderData = null;
            }
            if (this._subStruct) {
                this._subStruct._updateGlobalShaderData();
            }
        }
        _updatePriority() {
            if (this._pass) {
                if (this._maskParentPass) {
                    this._pass.priority = this._maskParentPass.priority + 1;
                }
                else if (this._parentData.pass) {
                    this._pass.priority = this._parentData.pass.priority + 1;
                }
                else {
                    this._pass.priority = 0;
                }
            }
        }
        setMaskParentPass(pass) {
            this._maskParentPass = pass;
            this._updatePriority();
            if (this._pass) {
                this.updateChildren(ChildrenUpdateType.Pass);
            }
        }
        get pass() {
            return this._pass || this._currentData.pass;
        }
        set pass(value) {
            if (value !== this._pass) {
                this._pass = value;
                this._updatePriority();
                this.updateChildren(ChildrenUpdateType.Pass);
            }
        }
        get subStruct() {
            return this._subStruct;
        }
        set subStruct(value) {
            if (value != this._subStruct) {
                let updateFlag = 0;
                if (value) {
                    let parentData = this._parentData;
                    value._blendMode = this._blendMode;
                    value._currentData = parentData;
                    value._maskParentPass = this._maskParentPass;
                    if (parentData.globalAlpha !== 1) {
                        updateFlag |= ChildrenUpdateType.Alpha;
                    }
                    if (!this._globalRenderData && parentData.globalRenderData) {
                        updateFlag |= ChildrenUpdateType.Global;
                    }
                    if (!this._clipInfo && parentData.clipInfo) {
                        updateFlag |= ChildrenUpdateType.Clip;
                    }
                    if (this._blendMode !== Laya.BlendMode.invalid || parentData.blendMode !== Laya.BlendMode.invalid) {
                        updateFlag |= ChildrenUpdateType.Blend;
                    }
                    this._blendMode = Laya.BlendMode.invalid;
                    this._currentData = _DefaultParentData;
                    value.needUploadAlpha = true;
                }
                else if (this._subStruct) {
                    let parentData = this._parentData;
                    this._subStruct._currentData = this._subStruct._parentData;
                    this._blendMode = this._subStruct._blendMode;
                    if (parentData.globalAlpha !== 1) {
                        updateFlag |= ChildrenUpdateType.Alpha;
                    }
                    if (!this._clipInfo && parentData.clipInfo) {
                        updateFlag |= ChildrenUpdateType.Clip;
                    }
                    if (!this._globalRenderData && parentData.globalRenderData) {
                        updateFlag |= ChildrenUpdateType.Global;
                    }
                    if (this._blendMode !== Laya.BlendMode.invalid || parentData.blendMode !== Laya.BlendMode.invalid) {
                        updateFlag |= ChildrenUpdateType.Blend;
                    }
                    this._subStruct._blendMode = Laya.BlendMode.invalid;
                    this._subStruct._maskParentPass = null;
                    this._currentData = parentData;
                }
                this._subStruct = value;
                this._updateGlobalShaderData();
                this.updateChildren(updateFlag);
                this._setBlendMode();
            }
        }
        constructor() {
            this.manualRender = false;
            this._parentData = Object.assign({}, _DefaultParentData);
            this._currentData = this._parentData;
            this.zIndex = 0;
            this._effectZ = 0;
            this.stackingRoot = false;
            this.rect = new Laya.Rectangle();
            this._enableCulling = false;
            this.renderLayer = 1;
            this.children = [];
            this.renderType = -1;
            this.renderUpdateMask = 0;
            this._alpha = 1.0;
            this._blendMode = Laya.BlendMode.invalid;
            this.needUploadClip = -1;
            this.needUploadAlpha = true;
            this.enabled = true;
            this.isRenderStruct = false;
            this.renderElements = null;
            this.spriteShaderData = null;
            this._globalShaderData = null;
            this._globalRenderData = null;
            this._clipRect = null;
            this._clipInfo = null;
            this._uniformClip = false;
            this._rnUpdateFun = null;
        }
        get _parentClipInfo() {
            return this._currentData.clipInfo;
        }
        setRenderUpdateCallback(func) {
            this._rnUpdateFun = func;
        }
        _handleInterData() {
            let rect = this._clipRect;
            if (rect) {
                let info = this._clipInfo;
                let trans = this.trans;
                let clipInfo = this._currentData.clipInfo;
                let parentClipUpdateFrame = clipInfo && clipInfo !== _DefaultClipInfo ? clipInfo._updateFrame : -1;
                if (trans) {
                    if (info._updateFrame < trans.modifiedFrame || info._updateFrame < parentClipUpdateFrame) {
                        let mat = trans.matrix;
                        let cm = info.clipMatrix;
                        let { x, y, width, height } = rect;
                        width = Math.max(width, 0.0001);
                        height = Math.max(height, 0.0001);
                        let tx = mat.tx, ty = mat.ty;
                        cm.tx = x * mat.a + y * mat.c + tx;
                        cm.ty = x * mat.b + y * mat.d + ty;
                        cm.a = width * mat.a;
                        cm.b = width * mat.b;
                        cm.c = height * mat.c;
                        cm.d = height * mat.d;
                        if (parentClipUpdateFrame !== -1) {
                            let parentClipPos = clipInfo.clipMatPos;
                            let offsetx = parentClipPos.z - parentClipPos.x;
                            let offsety = parentClipPos.w - parentClipPos.y;
                            let parentMat = clipInfo.clipMatrix;
                            let pmRot = parentMat.b !== 0 || parentMat.c !== 0;
                            let cmRot = cm.b !== 0 || cm.c !== 0;
                            if (!pmRot && !cmRot) {
                                if (cm.a > 0 && cm.d > 0) {
                                    let parentMinX = parentMat.tx;
                                    let parentMinY = parentMat.ty;
                                    let parentMaxX = parentMinX + parentMat.a;
                                    let parentMaxY = parentMinY + parentMat.d;
                                    let cmaxx = tx + cm.a;
                                    let cmaxy = ty + cm.d;
                                    if (cmaxx <= parentMinX || cmaxy <= parentMinY || tx >= parentMaxX || ty >= parentMaxY) {
                                        cm.a = -0.1;
                                        cm.d = -0.1;
                                    }
                                    else {
                                        if (tx < parentMinX) {
                                            cm.a -= (parentMinX - tx);
                                            tx = parentMinX;
                                        }
                                        if (cmaxx > parentMaxX) {
                                            cm.a -= (cmaxx - parentMaxX);
                                        }
                                        if (ty < parentMinY) {
                                            cm.d -= (parentMinY - ty);
                                            ty = parentMinY;
                                        }
                                        if (cmaxy > parentMaxY) {
                                            cm.d -= (cmaxy - parentMaxY);
                                        }
                                        if (cm.a <= 0)
                                            cm.a = -0.1;
                                        if (cm.d <= 0)
                                            cm.d = -0.1;
                                        if (cm.tx < parentMinX) {
                                            cm.tx = parentMinX;
                                        }
                                        if (cm.ty < parentMinY) {
                                            cm.ty = parentMinY;
                                        }
                                    }
                                }
                            }
                            else {
                                let det = parentMat.a * parentMat.d - parentMat.b * parentMat.c;
                                if (det === 0) {
                                    cm.a = -0.1;
                                    cm.b = 0;
                                    cm.c = 0;
                                    cm.d = -0.1;
                                }
                                else {
                                    let invDet = 1 / det;
                                    let dx0 = cm.tx - parentMat.tx, dy0 = cm.ty - parentMat.ty;
                                    let u0 = (parentMat.d * dx0 - parentMat.c * dy0) * invDet;
                                    let v0 = (-parentMat.b * dx0 + parentMat.a * dy0) * invDet;
                                    let du1 = (parentMat.d * cm.a - parentMat.c * cm.b) * invDet;
                                    let dv1 = (-parentMat.b * cm.a + parentMat.a * cm.b) * invDet;
                                    let du2 = (parentMat.d * cm.c - parentMat.c * cm.d) * invDet;
                                    let dv2 = (-parentMat.b * cm.c + parentMat.a * cm.d) * invDet;
                                    let du1N = du1 < 0 ? du1 : 0, du1P = du1 > 0 ? du1 : 0;
                                    let du2N = du2 < 0 ? du2 : 0, du2P = du2 > 0 ? du2 : 0;
                                    let dv1N = dv1 < 0 ? dv1 : 0, dv1P = dv1 > 0 ? dv1 : 0;
                                    let dv2N = dv2 < 0 ? dv2 : 0, dv2P = dv2 > 0 ? dv2 : 0;
                                    let cMinU = u0 + du1N + du2N, cMaxU = u0 + du1P + du2P;
                                    let cMinV = v0 + dv1N + dv2N, cMaxV = v0 + dv1P + dv2P;
                                    let iu0 = cMinU > 0 ? cMinU : 0;
                                    let iv0 = cMinV > 0 ? cMinV : 0;
                                    let iu1 = cMaxU < 1 ? cMaxU : 1;
                                    let iv1 = cMaxV < 1 ? cMaxV : 1;
                                    if (iu0 >= iu1 || iv0 >= iv1) {
                                        cm.a = -0.1;
                                        cm.b = 0;
                                        cm.c = 0;
                                        cm.d = -0.1;
                                    }
                                    else {
                                        let du = iu1 - iu0, dv = iv1 - iv0;
                                        cm.tx = parentMat.tx + iu0 * parentMat.a + iv0 * parentMat.c;
                                        cm.ty = parentMat.ty + iu0 * parentMat.b + iv0 * parentMat.d;
                                        cm.a = du * parentMat.a;
                                        cm.b = du * parentMat.b;
                                        cm.c = dv * parentMat.c;
                                        cm.d = dv * parentMat.d;
                                        tx = cm.tx;
                                        ty = cm.ty;
                                    }
                                }
                            }
                            tx += offsetx;
                            ty += offsety;
                        }
                        info.clipMatDir.setValue(cm.a, cm.b, cm.c, cm.d);
                        info.clipMatPos.setValue(cm.tx, cm.ty, tx, ty);
                        info._updateFrame = Math.max(trans.modifiedFrame, parentClipUpdateFrame);
                    }
                }
            }
            if (this._renderDataHandler) {
                let data = this.spriteShaderData;
                let info = this.getClipInfo();
                if (info !== _DefaultClipInfo) {
                    if (this.needUploadClip < info._updateFrame) {
                        data.setVector(Laya.ShaderDefines2D.UNIFORM_CLIPMATDIR, info.clipMatDir);
                        data.setVector(Laya.ShaderDefines2D.UNIFORM_CLIPMATPOS, info.clipMatPos);
                        this.needUploadClip = info._updateFrame;
                    }
                    if (!this._uniformClip) {
                        this._uniformClip = true;
                        data.addDefine(Laya.ShaderDefines2D.UNIFORMCLIP);
                    }
                }
                else if (this._uniformClip) {
                    data.removeDefine(Laya.ShaderDefines2D.UNIFORMCLIP);
                    this._uniformClip = false;
                }
                if (this.needUploadAlpha) {
                    data.setNumber(Laya.ShaderDefines2D.UNIFORM_VERTALPHA, this.globalAlpha);
                    this.needUploadAlpha = false;
                }
            }
        }
        _setBlendMode() {
            if (!this.spriteShaderData)
                return;
            Laya.BlendModeHandler.setShaderData(this.blendMode, this.spriteShaderData);
            if (this._subStruct) {
                this._subStruct._setBlendMode();
            }
        }
        setClipRect(rect) {
            this._clipRect = rect;
            rect ? this._initClipInfo() : this._clipInfo = null;
            this.updateChildren(ChildrenUpdateType.Clip);
        }
        _initClipInfo() {
            if (!this._clipInfo) {
                this._clipInfo = {
                    clipMatDir: new Laya.Vector4,
                    clipMatPos: new Laya.Vector4,
                    clipMatrix: new Laya.Matrix,
                    _updateFrame: -1
                };
            }
            else
                this._clipInfo._updateFrame = -1;
        }
        _updateGlobalAlpha(value, parentAlpha = 1) {
            this._parentData.globalAlpha = parentAlpha * value;
        }
        _updateBlendMode(blendMode) {
            if (this._subStruct && this._subStruct.enabled) {
                this._subStruct._blendMode = blendMode;
            }
            else {
                this._blendMode = blendMode;
            }
        }
        getClipInfo() {
            return this._clipInfo || this._currentData.clipInfo || _DefaultClipInfo;
        }
        hasClip() {
            return this.getClipInfo() !== _DefaultClipInfo;
        }
        updateChildren(type) {
            if (type == ChildrenUpdateType.None)
                return;
            let info, blendMode, alpha;
            let priority = 0, pass = null, enableCulling = false, dcOptimize = false;
            let globalRenderData = null;
            let updateBlend = false, updateClip = false, updateAlpha = false, updatePass = false, updateGlobal = false, updateCulling = false, updateDcOptimize = false;
            if (type & ChildrenUpdateType.Clip) {
                info = this.getClipInfo();
                this.needUploadClip = -1;
                if (this._subStruct) {
                    this._subStruct.needUploadClip = -1;
                }
                updateClip = true;
            }
            if (type & ChildrenUpdateType.Blend) {
                blendMode = this.blendMode;
                updateBlend = true;
            }
            if (type & ChildrenUpdateType.Alpha) {
                alpha = this.globalAlpha;
                this.needUploadAlpha = true;
                if (this._subStruct) {
                    this._subStruct.needUploadAlpha = true;
                }
                updateAlpha = true;
            }
            if (type & ChildrenUpdateType.Pass) {
                pass = this.pass;
                priority = pass ? pass.priority + 1 : 0;
                updatePass = true;
            }
            if (type & ChildrenUpdateType.Global) {
                updateGlobal = true;
                this._globalShaderData;
                globalRenderData = this.globalRenderData;
            }
            if (type & ChildrenUpdateType.Culling) {
                updateCulling = true;
                enableCulling = this.inheritedEnableCulling;
            }
            if (type & ChildrenUpdateType.DcOptimize) {
                updateDcOptimize = true;
                dcOptimize = this.inheritedDcOptimize;
            }
            for (const child of this.children) {
                let updateChild = false;
                let childParentData = child._parentData;
                if (updateClip) {
                    childParentData.clipInfo = info;
                    if (!child._clipInfo) {
                        updateChild = true;
                    }
                }
                if (updateBlend) {
                    if (child._blendMode === Laya.BlendMode.invalid) {
                        childParentData.blendMode = blendMode;
                        child._setBlendMode();
                        updateChild = true;
                    }
                }
                if (updateAlpha) {
                    child._updateGlobalAlpha(child.alpha, alpha);
                    updateChild = true;
                }
                if (updatePass) {
                    childParentData.pass = pass;
                    if (child._pass && child._pass !== pass) {
                        child._pass.priority = priority;
                    }
                    updateChild = true;
                }
                if (updateGlobal) {
                    childParentData.globalRenderData = globalRenderData;
                    child._updateGlobalShaderData();
                    if (!child._globalRenderData) {
                        updateChild = true;
                    }
                }
                if (updateCulling) {
                    childParentData.enableCulling = enableCulling;
                    if (child._pass) {
                        child._pass.repaint = true;
                    }
                    updateChild = true;
                }
                if (updateDcOptimize) {
                    childParentData.dcOptimize = dcOptimize;
                    if (child._pass) {
                        child._pass.repaint = true;
                    }
                    updateChild = true;
                }
                if (updateChild) {
                    child.updateChildren(type);
                }
            }
        }
        setRepaint() {
            if (this.pass) {
                this.pass.repaint = true;
            }
        }
        addChild(child, index) {
            child.parent = this;
            this.children.splice(index, 0, child);
            let childParentData = child._parentData;
            childParentData.clipInfo = this.getClipInfo();
            childParentData.blendMode = this.blendMode;
            child._setBlendMode();
            child._updateGlobalAlpha(child.alpha, this.globalAlpha);
            let parentPass = this.pass;
            childParentData.pass = parentPass;
            child._updatePriority();
            childParentData.globalRenderData = this.globalRenderData;
            child._updateGlobalShaderData();
            childParentData.enableCulling = this.inheritedEnableCulling;
            childParentData.dcOptimize = this.inheritedDcOptimize;
            child.updateChildren(ChildrenUpdateType.All);
            return;
        }
        updateChildIndex(child, oldIndex, index) {
            if (oldIndex === index)
                return;
            this.children.splice(oldIndex, 1);
            if (index >= this.children.length) {
                this.children.push(child);
            }
            else {
                this.children.splice(index, 0, child);
            }
        }
        removeChild(child) {
            const index = this.children.indexOf(child);
            if (index !== -1) {
                child.parent = null;
                this.children.splice(index, 1);
                let childParentData = child._parentData;
                childParentData.pass = null;
                child._updatePriority();
                childParentData.clipInfo = null;
                childParentData.blendMode = Laya.BlendMode.invalid;
                child._updateGlobalAlpha(child._alpha);
                childParentData.globalRenderData = null;
                child._updateGlobalShaderData();
                childParentData.enableCulling = false;
                childParentData.dcOptimize = false;
                child.updateChildren(ChildrenUpdateType.All);
            }
        }
        renderUpdate(context) {
            if (this.renderDataHandler) {
                this.renderDataHandler.inheriteRenderData(context);
            }
            if (this._rnUpdateFun) {
                this._rnUpdateFun(context);
            }
        }
        destroy() {
            this._clipInfo = null;
            this._currentData = null;
            this._parentData = null;
            this._clipRect = null;
            this.renderElements = null;
            this.spriteShaderData = null;
            this.parent = null;
            this.children.length = 0;
            this.children = null;
            this._pass = null;
        }
    }

    class WebDefineDatas {
        constructor() {
            this._changeFlags = new Set();
            this._mask = [];
            this._length = 0;
        }
        _intersectionDefineDatas(define) {
            var unionMask = define._mask;
            var mask = this._mask;
            for (var i = this._length - 1; i >= 0; i--) {
                var value = mask[i] & unionMask[i];
                if (value === 0 && i === this._length - 1)
                    this._length--;
                else
                    mask[i] = value;
            }
        }
        add(define) {
            let changed = false;
            var index = define._index;
            var size = index + 1;
            var mask = this._mask;
            var maskStart = this._length;
            if (maskStart < size) {
                (mask.length < size) && (mask.length = size);
                for (; maskStart < index; maskStart++)
                    mask[maskStart] = 0;
                mask[index] = define._value;
                this._length = size;
                changed = true;
            }
            else {
                let last = mask[index];
                mask[index] |= define._value;
                changed = last != mask[index];
            }
            if (changed) {
                this._notifyChangeFlag();
            }
            return changed;
        }
        remove(define) {
            var index = define._index;
            var mask = this._mask;
            var endIndex = this._length - 1;
            if (index > endIndex)
                return false;
            let lastValue = mask[index];
            var newValue = mask[index] & ~define._value;
            if (index == endIndex && newValue === 0)
                this._length--;
            else
                mask[index] = newValue;
            let changed = lastValue != newValue;
            if (changed) {
                this._notifyChangeFlag();
            }
            return changed;
        }
        addDefineDatas(define) {
            var addMask = define._mask;
            var size = define._length;
            var mask = this._mask;
            var maskStart = this._length;
            if (maskStart < size) {
                mask.length = size;
                for (var i = 0; i < maskStart; i++)
                    mask[i] |= addMask[i];
                for (; i < size; i++)
                    mask[i] = addMask[i];
                this._length = size;
            }
            else {
                for (var i = 0; i < size; i++) {
                    mask[i] |= addMask[i];
                }
            }
            this._notifyChangeFlag();
        }
        removeDefineDatas(define) {
            var removeMask = define._mask;
            var mask = this._mask;
            var endIndex = this._length - 1;
            var i = Math.min(define._length, endIndex);
            for (; i >= 0; i--) {
                var newValue = mask[i] & ~removeMask[i];
                if (i == endIndex && newValue === 0) {
                    endIndex--;
                    this._length--;
                }
                else {
                    mask[i] = newValue;
                }
            }
            this._notifyChangeFlag();
        }
        has(define) {
            var index = define._index;
            if (index >= this._length)
                return false;
            return (this._mask[index] & define._value) !== 0;
        }
        _notifyChangeFlag() {
            if (this._changeFlags.size > 0) {
                this._changeFlags.forEach(value => {
                    value.setValue(Laya.Stat.loopCount, Laya.LayaGL.renderEngine._framePassCount);
                });
            }
        }
        addChangeFlagInfo(flag) {
            if (!this._changeFlags.has(flag)) {
                flag.setValue(Laya.Stat.loopCount, Laya.LayaGL.renderEngine._framePassCount);
                this._changeFlags.add(flag);
            }
        }
        removeChangeFlagInfo(flag) {
            if (this._changeFlags.has(flag)) {
                flag.setValue(Laya.Stat.loopCount, Laya.LayaGL.renderEngine._framePassCount);
                this._changeFlags.delete(flag);
            }
        }
        clear() {
            this._length = 0;
            this._notifyChangeFlag();
        }
        cloneTo(destObject) {
            var destMask = destObject._mask;
            var mask = this._mask;
            var count = this._length;
            destMask.length = count;
            for (var i = 0; i < count; i++)
                destMask[i] = mask[i];
            destObject._length = count;
            destObject._notifyChangeFlag();
        }
        clone() {
            var dest = new WebDefineDatas();
            this.cloneTo(dest);
            return dest;
        }
        destroy() {
            delete this._mask;
        }
        isEual(other) {
            var count = this._length;
            if (count != other._length)
                return false;
            let mask = this._mask;
            let otherMask = other._mask;
            for (var i = 0; i < count; i++)
                if (mask[i] != otherMask[i])
                    return false;
            return true;
        }
    }

    exports.WebGLExtension = void 0;
    (function (WebGLExtension) {
        WebGLExtension[WebGLExtension["OES_vertex_array_object"] = 0] = "OES_vertex_array_object";
        WebGLExtension[WebGLExtension["ANGLE_instanced_arrays"] = 1] = "ANGLE_instanced_arrays";
        WebGLExtension[WebGLExtension["OES_texture_half_float"] = 2] = "OES_texture_half_float";
        WebGLExtension[WebGLExtension["OES_texture_half_float_linear"] = 3] = "OES_texture_half_float_linear";
        WebGLExtension[WebGLExtension["OES_texture_float"] = 4] = "OES_texture_float";
        WebGLExtension[WebGLExtension["OES_element_index_uint"] = 5] = "OES_element_index_uint";
        WebGLExtension[WebGLExtension["OES_texture_float_linear"] = 6] = "OES_texture_float_linear";
        WebGLExtension[WebGLExtension["EXT_color_buffer_half_float"] = 7] = "EXT_color_buffer_half_float";
        WebGLExtension[WebGLExtension["EXT_shader_texture_lod"] = 8] = "EXT_shader_texture_lod";
        WebGLExtension[WebGLExtension["WEBGL_depth_texture"] = 9] = "WEBGL_depth_texture";
        WebGLExtension[WebGLExtension["EXT_sRGB"] = 10] = "EXT_sRGB";
        WebGLExtension[WebGLExtension["EXT_color_buffer_float"] = 11] = "EXT_color_buffer_float";
        WebGLExtension[WebGLExtension["EXT_texture_filter_anisotropic"] = 12] = "EXT_texture_filter_anisotropic";
        WebGLExtension[WebGLExtension["WEBGL_compressed_texture_s3tc"] = 13] = "WEBGL_compressed_texture_s3tc";
        WebGLExtension[WebGLExtension["WEBGL_compressed_texture_s3tc_srgb"] = 14] = "WEBGL_compressed_texture_s3tc_srgb";
        WebGLExtension[WebGLExtension["WEBGL_compressed_texture_pvrtc"] = 15] = "WEBGL_compressed_texture_pvrtc";
        WebGLExtension[WebGLExtension["WEBGL_compressed_texture_etc1"] = 16] = "WEBGL_compressed_texture_etc1";
        WebGLExtension[WebGLExtension["WEBGL_compressed_texture_etc"] = 17] = "WEBGL_compressed_texture_etc";
        WebGLExtension[WebGLExtension["WEBGL_compressed_texture_astc"] = 18] = "WEBGL_compressed_texture_astc";
        WebGLExtension[WebGLExtension["OES_standard_derivatives"] = 19] = "OES_standard_derivatives";
    })(exports.WebGLExtension || (exports.WebGLExtension = {}));

    class GLObject {
        constructor(engine) {
            this._destroyed = false;
            this._engine = engine;
            this._gl = this._engine.gl;
            this._id = this._engine._IDCounter++;
        }
        get destroyed() {
            return this._destroyed;
        }
        destroy() {
            if (this._destroyed)
                return;
            this._destroyed = true;
        }
    }

    class WebGLInternalRT extends GLObject {
        get gpuMemory() {
            return this._gpuMemory;
        }
        set gpuMemory(value) {
            this._changeTexMemory(value);
            this._gpuMemory = value;
        }
        _changeTexMemory(value) {
            Laya.LayaGL.statAgent.recordMemoryData(Laya.StatElement.M_GPUMemory, -this._gpuMemory + value);
            Laya.LayaGL.statAgent.recordMemoryData(Laya.StatElement.M_RenderTexture, -this._gpuMemory + value);
            Laya.LayaGL.statAgent.recordMemoryData(Laya.StatElement.M_AllTexture, -this._gpuMemory + value);
        }
        constructor(engine, colorFormat, depthStencilFormat, isCube, generateMipmap, samples) {
            super(engine);
            this._gpuMemory = 0;
            this.colorFormat = colorFormat;
            this.depthStencilFormat = depthStencilFormat;
            this._isCube = isCube;
            this._generateMipmap = generateMipmap;
            this._samples = samples;
            this._textures = [];
            this._depthTexture = null;
            this._framebuffer = this._gl.createFramebuffer();
            if (samples > 1) {
                this._msaaFramebuffer = this._gl.createFramebuffer();
            }
            Laya.LayaGL.statAgent.recordCountData(Laya.StatElement.C_RenderTexture, 1);
        }
        _getSource() {
            return this._textures[0].resource;
        }
        dispose() {
            this._textures.forEach(tex => {
                tex && tex.dispose();
            });
            this._textures = null;
            this._depthTexture && this._depthTexture.dispose();
            this._depthTexture = null;
            this._framebuffer && this._gl.deleteFramebuffer(this._framebuffer);
            this._framebuffer = null;
            this._depthbuffer && this._gl.deleteRenderbuffer(this._depthbuffer);
            this._depthbuffer = null;
            this._msaaFramebuffer && this._gl.deleteFramebuffer(this._msaaFramebuffer);
            this._msaaFramebuffer = null;
            this._msaaRenderbuffer && this._gl.deleteRenderbuffer(this._msaaRenderbuffer);
            this._msaaRenderbuffer = null;
            this._changeTexMemory(0);
            this._gpuMemory = 0;
            Laya.LayaGL.statAgent.recordCountData(Laya.StatElement.C_RenderTexture, -1);
        }
    }

    class WebGLInternalTex extends GLObject {
        get mipmap() {
            return this._mipmap;
        }
        get mipmapCount() {
            return this._mipmapCount;
        }
        _getSource() {
            return this.resource;
        }
        get gpuMemory() {
            return this._gpuMemory;
        }
        set gpuMemory(value) {
            this._changeTexMemory(value);
            this._gpuMemory = value;
        }
        constructor(engine, target, width, height, depth, dimension, mipmap, useSRGBLoader, gammaCorrection) {
            super(engine);
            this._gpuMemory = 0;
            this._baseMipmapLevel = 0;
            this._maxMipmapLevel = 0;
            this.resource = this._gl.createTexture();
            this.width = width;
            this.height = height;
            this.depth = depth;
            const isPot = (value) => {
                return (value & (value - 1)) === 0;
            };
            this.isPotSize = isPot(width) && isPot(height);
            if (dimension == Laya.TextureDimension.Tex3D) {
                this.isPotSize = this.isPotSize && isPot(this.depth);
            }
            switch (dimension) {
                case Laya.TextureDimension.Tex2D:
                    this._statistics_M_Texture = Laya.StatElement.M_Texture2D;
                    this._statistics_RC_Texture = Laya.StatElement.C_Texture2D;
                    break;
                case Laya.TextureDimension.Tex3D:
                    this._statistics_M_Texture = Laya.StatElement.M_Texture3D;
                    this._statistics_RC_Texture = Laya.StatElement.C_Texture3D;
                    break;
                case Laya.TextureDimension.Cube:
                    this._statistics_M_Texture = Laya.StatElement.M_TextureCube;
                    this._statistics_RC_Texture = Laya.StatElement.C_TextureCube;
                    break;
                case Laya.TextureDimension.Texture2DArray:
                    this._statistics_M_Texture = Laya.StatElement.M_Texture2DArray;
                    this._statistics_RC_Texture = Laya.StatElement.C_Texture2DArray;
                    break;
            }
            this._mipmap = mipmap && this.isPotSize;
            this._mipmapCount = this._mipmap ? Math.max(Math.ceil(Math.log2(width)) + 1, Math.ceil(Math.log2(height)) + 1) : 1;
            this._maxMipmapLevel = this._mipmapCount - 1;
            this._baseMipmapLevel = 0;
            this.useSRGBLoad = useSRGBLoader;
            this.gammaCorrection = gammaCorrection;
            this.target = target;
            this.filterMode = Laya.FilterMode.Bilinear;
            this.wrapU = Laya.WrapMode.Repeat;
            this.wrapV = Laya.WrapMode.Repeat;
            this.wrapW = Laya.WrapMode.Repeat;
            this.anisoLevel = 4;
            this.compareMode = Laya.TextureCompareMode.None;
            Laya.LayaGL.statAgent.recordCountData(this._statistics_RC_Texture, 1);
            Laya.LayaGL.statAgent.recordCountData(Laya.StatElement.C_AllTexture, 1);
        }
        get filterMode() {
            return this._filterMode;
        }
        set filterMode(value) {
            if (this._filterMode != value && this.resource) {
                let gl = this._gl;
                let mipmap = this.mipmap;
                let min = this.getFilteMinrParam(value, mipmap);
                this._setTexParameteri(gl.TEXTURE_MIN_FILTER, min);
                let mag = this.getFilterMagParam(value);
                this._setTexParameteri(gl.TEXTURE_MAG_FILTER, mag);
                this._filterMode = value;
            }
        }
        get wrapU() {
            return this._warpU;
        }
        set wrapU(value) {
            if (this._warpU != value && this.resource) {
                let gl = this._gl;
                let warpParam = this.getWrapParam(value);
                this._setWrapMode(gl.TEXTURE_WRAP_S, warpParam);
                this._warpU = value;
            }
        }
        get wrapV() {
            return this._warpV;
        }
        set wrapV(value) {
            if (this._warpV != value && this.resource) {
                let gl = this._gl;
                let warpParam = this.getWrapParam(value);
                this._setWrapMode(gl.TEXTURE_WRAP_T, warpParam);
                this._warpV = value;
            }
        }
        get wrapW() {
            return this._warpW;
        }
        set wrapW(value) {
            if (this._warpW != value && this.resource) {
                if (this._engine.getCapable(Laya.RenderCapable.Texture3D)) {
                    let gl = this._gl;
                    let warpParam = this.getWrapParam(value);
                    this._setWrapMode(gl.TEXTURE_WRAP_R, warpParam);
                }
                this._warpW = value;
            }
        }
        get anisoLevel() {
            return this._anisoLevel;
        }
        set anisoLevel(value) {
            let anisoExt = this._engine._supportCapatable.getExtension(exports.WebGLExtension.EXT_texture_filter_anisotropic);
            if (anisoExt) {
                this._gl;
                let maxAnisoLevel = this._engine.getParams(Laya.RenderParams.Max_AnisoLevel_Count);
                let level = Math.max(1, Math.min(maxAnisoLevel, value));
                this._setTexParametexf(anisoExt.TEXTURE_MAX_ANISOTROPY_EXT, level);
                this._anisoLevel = level;
            }
            else {
                this._anisoLevel = 1;
            }
        }
        set baseMipmapLevel(value) {
            if (this._engine.isWebGL2) {
                this._setTexParameteri(this._gl.TEXTURE_BASE_LEVEL, value);
            }
            this._baseMipmapLevel = value;
        }
        get baseMipmapLevel() {
            return this._baseMipmapLevel;
        }
        set maxMipmapLevel(value) {
            if (this._engine.isWebGL2) {
                this._setTexParameteri(this._gl.TEXTURE_MAX_LEVEL, value);
            }
            this._maxMipmapLevel = value;
        }
        get maxMipmapLevel() {
            return this._maxMipmapLevel;
        }
        get compareMode() {
            return this._compareMode;
        }
        set compareMode(value) {
            this._compareMode = value;
        }
        _setTexParameteri(pname, param) {
            let gl = this._gl;
            let target = this.target;
            this._engine._bindTexture(target, this.resource);
            gl.texParameteri(target, pname, param);
            this._engine._bindTexture(target, null);
        }
        _setTexParametexf(pname, param) {
            let gl = this._gl;
            let target = this.target;
            this._engine._bindTexture(target, this.resource);
            gl.texParameterf(target, pname, param);
            this._engine._bindTexture(target, null);
        }
        getFilteMinrParam(filterMode, mipmap) {
            let gl = this._gl;
            switch (filterMode) {
                case Laya.FilterMode.Point:
                    return mipmap ? gl.NEAREST_MIPMAP_NEAREST : gl.NEAREST;
                case Laya.FilterMode.Bilinear:
                    return mipmap ? gl.LINEAR_MIPMAP_NEAREST : gl.LINEAR;
                case Laya.FilterMode.Trilinear:
                    return mipmap ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR;
                default:
                    return mipmap ? gl.LINEAR_MIPMAP_NEAREST : gl.LINEAR;
            }
        }
        getFilterMagParam(filterMode) {
            let gl = this._gl;
            switch (filterMode) {
                case Laya.FilterMode.Point:
                    return gl.NEAREST;
                case Laya.FilterMode.Bilinear:
                    return gl.LINEAR;
                case Laya.FilterMode.Trilinear:
                    return gl.LINEAR;
                default:
                    return gl.LINEAR;
            }
        }
        getWrapParam(wrapMode) {
            let gl = this._gl;
            switch (wrapMode) {
                case Laya.WrapMode.Repeat:
                    return gl.REPEAT;
                case Laya.WrapMode.Clamp:
                    return gl.CLAMP_TO_EDGE;
                case Laya.WrapMode.Mirrored:
                    return gl.MIRRORED_REPEAT;
                default:
                    return gl.REPEAT;
            }
        }
        _setWrapMode(pname, param) {
            let gl = this._gl;
            if (!this.isPotSize) {
                param = gl.CLAMP_TO_EDGE;
            }
            this._setTexParameteri(pname, param);
        }
        _changeTexMemory(memory) {
            Laya.LayaGL.statAgent.recordMemoryData(Laya.StatElement.M_GPUMemory, -this._gpuMemory + memory);
            Laya.LayaGL.statAgent.recordMemoryData(Laya.StatElement.M_AllTexture, -this._gpuMemory + memory);
            Laya.LayaGL.statAgent.recordMemoryData(this._statistics_M_Texture, -this._gpuMemory + memory);
        }
        dispose() {
            let gl = this._gl;
            gl.deleteTexture(this.resource);
            this._changeTexMemory(0);
            this._gpuMemory = 0;
            Laya.LayaGL.statAgent.recordCountData(this._statistics_RC_Texture, -1);
            Laya.LayaGL.statAgent.recordCountData(Laya.StatElement.C_AllTexture, -1);
        }
    }

    class GLTextureContext extends GLObject {
        constructor(engine) {
            super(engine);
            this._glParam = {
                internalFormat: 0,
                format: 0,
                type: 0,
            };
            this.needBitmap = false;
            this._sRGB = this._engine._supportCapatable.getExtension(exports.WebGLExtension.EXT_sRGB);
            this._oesTextureHalfFloat = this._engine._supportCapatable.getExtension(exports.WebGLExtension.OES_texture_half_float);
            this._compressdTextureS3tc_srgb = this._engine._supportCapatable.getExtension(exports.WebGLExtension.WEBGL_compressed_texture_s3tc_srgb);
            this._compressedTextureEtc1 = this._engine._supportCapatable.getExtension(exports.WebGLExtension.WEBGL_compressed_texture_etc1);
            this._compressedTextureS3tc = this._engine._supportCapatable.getExtension(exports.WebGLExtension.WEBGL_compressed_texture_s3tc);
            this._compressedTextureETC = this._engine._supportCapatable.getExtension(exports.WebGLExtension.WEBGL_compressed_texture_etc);
            this._compressedTextureASTC = this._engine._supportCapatable.getExtension(exports.WebGLExtension.WEBGL_compressed_texture_astc);
            this._webgl_depth_texture = this._engine._supportCapatable.getExtension(exports.WebGLExtension.WEBGL_depth_texture);
        }
        createRenderTargetFromArrayLayer(arrayTex, layer, colorFormat, depthStencilFormat, sRGB) {
            throw new Error("Method not implemented.");
        }
        createTexture3DInternal(dimension, width, height, depth, format, generateMipmap, sRGB, premultipliedAlpha) {
            return null;
        }
        setTexture3DImageData(texture, source, depth, premultiplyAlpha, invertY) {
            return null;
        }
        setTexture3DPixelsData(texture, source, depth, premultiplyAlpha, invertY) {
            return null;
        }
        setTexture3DSubPixelsData(texture, source, mipmapLevel, generateMipmap, xOffset, yOffset, zOffset, width, height, depth, premultiplyAlpha, invertY) {
            return null;
        }
        glTextureParam(format, useSRGB) {
            let gl = this._gl;
            this._glParam.internalFormat = null;
            this._glParam.format = null;
            this._glParam.type = null;
            switch (format) {
                case Laya.TextureFormat.Alpha8:
                    this._glParam.internalFormat = gl.ALPHA;
                    this._glParam.format = gl.ALPHA;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.R8G8B8:
                    this._glParam.internalFormat = useSRGB ? this._sRGB.SRGB_EXT : gl.RGB;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.R8G8B8A8:
                    this._glParam.internalFormat = useSRGB ? this._sRGB.SRGB_ALPHA_EXT : gl.RGBA;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.R5G6B5:
                    this._glParam.internalFormat = gl.RGB;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_SHORT_5_6_5;
                    break;
                case Laya.TextureFormat.R32G32B32A32:
                    this._glParam.internalFormat = gl.RGBA;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.FLOAT;
                    break;
                case Laya.TextureFormat.R32G32B32:
                    this._glParam.internalFormat = gl.RGB;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.FLOAT;
                    break;
                case Laya.TextureFormat.R16G16B16A16:
                    this._glParam.internalFormat = gl.RGBA;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = this._oesTextureHalfFloat.HALF_FLOAT_OES;
                    break;
                case Laya.TextureFormat.R16G16B16:
                    this._glParam.internalFormat = gl.RGB;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = this._oesTextureHalfFloat.HALF_FLOAT_OES;
                    break;
                case Laya.TextureFormat.DXT1:
                    this._glParam.internalFormat = useSRGB ? this._compressdTextureS3tc_srgb.COMPRESSED_SRGB_ALPHA_S3TC_DXT1_EXT : this._compressedTextureS3tc.COMPRESSED_RGBA_S3TC_DXT1_EXT;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.DXT3:
                    this._glParam.internalFormat = useSRGB ? this._compressdTextureS3tc_srgb.COMPRESSED_SRGB_ALPHA_S3TC_DXT3_EXT : this._compressedTextureS3tc.COMPRESSED_RGBA_S3TC_DXT3_EXT;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.DXT5:
                    this._glParam.internalFormat = useSRGB ? this._compressdTextureS3tc_srgb.COMPRESSED_SRGB_ALPHA_S3TC_DXT5_EXT : this._compressedTextureS3tc.COMPRESSED_RGBA_S3TC_DXT5_EXT;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ETC1RGB:
                    this._glParam.internalFormat = this._compressedTextureEtc1.COMPRESSED_RGB_ETC1_WEBGL;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ETC2RGBA:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_RGBA8_ETC2_EAC;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ETC2RGB:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_RGB8_ETC2;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ETC2SRGB:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_SRGB8_ETC2;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ETC2SRGB_Alpha8:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_SRGB8_ALPHA8_ETC2_EAC;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ETC2RGB_Alpha1:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_RGB8_PUNCHTHROUGH_ALPHA1_ETC2;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ETC2SRGB_Alpha1:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_SRGB8_PUNCHTHROUGH_ALPHA1_ETC2;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ASTC4x4:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_RGBA_ASTC_4x4_KHR;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ASTC6x6:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_RGBA_ASTC_6x6_KHR;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ASTC8x8:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_RGBA_ASTC_8x8_KHR;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ASTC10x10:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_RGBA_ASTC_10x10_KHR;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ASTC12x12:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_RGBA_ASTC_12x12_KHR;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ASTC4x4SRGB:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_SRGB8_ALPHA8_ASTC_4x4_KHR;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ASTC6x6SRGB:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_SRGB8_ALPHA8_ASTC_6x6_KHR;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ASTC8x8SRGB:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_SRGB8_ALPHA8_ASTC_8x8_KHR;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ASTC10x10SRGB:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_SRGB8_ALPHA8_ASTC_10x10_KHR;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.ASTC12x12SRGB:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_SRGB8_ALPHA8_ASTC_12x12_KHR;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                default:
                    throw "Unknown Texture Format.";
            }
            return this._glParam;
        }
        glRenderTextureParam(format, useSRGB) {
            let gl = this._gl;
            this._glParam.internalFormat = null;
            this._glParam.format = null;
            this._glParam.type = null;
            switch (format) {
                case Laya.RenderTargetFormat.R8G8B8:
                    this._glParam.internalFormat = useSRGB ? this._sRGB.SRGB_EXT : gl.RGB;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.RenderTargetFormat.R8G8B8A8:
                    this._glParam.internalFormat = useSRGB ? this._sRGB.SRGB_EXT : gl.RGBA;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.RenderTargetFormat.R16G16B16:
                    this._glParam.internalFormat = gl.RGB;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = this._oesTextureHalfFloat.HALF_FLOAT_OES;
                    break;
                case Laya.RenderTargetFormat.R16G16B16A16:
                    this._glParam.internalFormat = gl.RGBA;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = this._oesTextureHalfFloat.HALF_FLOAT_OES;
                    break;
                case Laya.RenderTargetFormat.R32G32B32:
                    this._glParam.internalFormat = gl.RGB;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.FLOAT;
                    break;
                case Laya.RenderTargetFormat.R32G32B32A32:
                    this._glParam.internalFormat = gl.RGBA;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.FLOAT;
                    break;
                case Laya.RenderTargetFormat.DEPTH_16:
                    this._glParam.internalFormat = gl.DEPTH_COMPONENT;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_SHORT;
                    break;
                case Laya.RenderTargetFormat.DEPTHSTENCIL_24_8:
                    this._glParam.internalFormat = gl.DEPTH_STENCIL;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = this._webgl_depth_texture.UNSIGNED_INT_24_8_WEBGL;
                    break;
                case Laya.RenderTargetFormat.DEPTH_32:
                    this._glParam.internalFormat = gl.DEPTH_COMPONENT;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_INT;
                    break;
                case Laya.RenderTargetFormat.STENCIL_8:
                default:
                    throw "render texture format wrong.";
            }
            return this._glParam;
        }
        glRenderBufferParam(format, useSRGB) {
            let gl = this._gl;
            switch (format) {
                case Laya.RenderTargetFormat.DEPTH_16:
                    return { internalFormat: gl.DEPTH_COMPONENT16, attachment: gl.DEPTH_ATTACHMENT };
                case Laya.RenderTargetFormat.DEPTHSTENCIL_24_8:
                    return { internalFormat: gl.DEPTH_STENCIL, attachment: gl.DEPTH_STENCIL_ATTACHMENT };
                case Laya.RenderTargetFormat.DEPTH_32:
                    return { internalFormat: gl.DEPTH_STENCIL, attachment: gl.DEPTH_STENCIL_ATTACHMENT };
                case Laya.RenderTargetFormat.STENCIL_8:
                    return { internalFormat: gl.STENCIL_INDEX8, attachment: gl.STENCIL_ATTACHMENT };
                default:
                    return null;
            }
        }
        glRenderTargetAttachment(format) {
            let gl = this._gl;
            switch (format) {
                case Laya.RenderTargetFormat.DEPTH_16:
                    return gl.DEPTH_ATTACHMENT;
                case Laya.RenderTargetFormat.DEPTHSTENCIL_24_8:
                    return gl.DEPTH_STENCIL_ATTACHMENT;
                case Laya.RenderTargetFormat.DEPTH_32:
                    return gl.DEPTH_ATTACHMENT;
                case Laya.RenderTargetFormat.STENCIL_8:
                    return gl.STENCIL_ATTACHMENT;
                case Laya.RenderTargetFormat.R8G8B8:
                case Laya.RenderTargetFormat.R8G8B8A8:
                case Laya.RenderTargetFormat.R16G16B16:
                case Laya.RenderTargetFormat.R16G16B16A16:
                case Laya.RenderTargetFormat.R32G32B32:
                case Laya.RenderTargetFormat.R32G32B32A32:
                    return gl.COLOR_ATTACHMENT0;
                default:
                    throw "render format.";
            }
        }
        getTarget(dimension) {
            let gl = this._gl;
            switch (dimension) {
                case Laya.TextureDimension.Tex2D:
                    return gl.TEXTURE_2D;
                case Laya.TextureDimension.Cube:
                    return gl.TEXTURE_CUBE_MAP;
                default:
                    throw "texture dimension wrong in WebGL1.";
            }
        }
        getFormatPixelsParams(format) {
            let formatParams = {
                channels: 0,
                bytesPerPixel: 0,
                dataTypedCons: Uint8Array,
                typedSize: 1
            };
            switch (format) {
                case Laya.TextureFormat.Alpha8:
                    formatParams.channels = 1;
                    formatParams.bytesPerPixel = 1;
                    formatParams.dataTypedCons = Uint8Array;
                    formatParams.typedSize = 1;
                    return formatParams;
                case Laya.TextureFormat.R8G8B8A8:
                    formatParams.channels = 4;
                    formatParams.bytesPerPixel = 4;
                    formatParams.dataTypedCons = Uint8Array;
                    formatParams.typedSize = 1;
                    return formatParams;
                case Laya.TextureFormat.R8G8B8:
                    formatParams.channels = 3;
                    formatParams.bytesPerPixel = 3;
                    formatParams.dataTypedCons = Uint8Array;
                    formatParams.typedSize = 1;
                    return formatParams;
                case Laya.TextureFormat.R5G6B5:
                    formatParams.channels = 3;
                    formatParams.bytesPerPixel = 2;
                    formatParams.dataTypedCons = Uint16Array;
                    formatParams.typedSize = 2;
                    return formatParams;
                case Laya.TextureFormat.R16G16B16:
                    formatParams.channels = 3;
                    formatParams.bytesPerPixel = 6;
                    formatParams.dataTypedCons = Uint16Array;
                    formatParams.typedSize = 2;
                    return formatParams;
                case Laya.TextureFormat.R16G16B16A16:
                    formatParams.channels = 4;
                    formatParams.bytesPerPixel = 8;
                    formatParams.dataTypedCons = Uint16Array;
                    formatParams.typedSize = 2;
                    return formatParams;
                case Laya.TextureFormat.R32G32B32:
                    formatParams.channels = 3;
                    formatParams.bytesPerPixel = 12;
                    formatParams.dataTypedCons = Float32Array;
                    formatParams.typedSize = 4;
                    return formatParams;
                case Laya.TextureFormat.R32G32B32A32:
                    formatParams.channels = 4;
                    formatParams.bytesPerPixel = 16;
                    formatParams.dataTypedCons = Float32Array;
                    formatParams.typedSize = 4;
                    return formatParams;
                default:
                    return formatParams;
            }
        }
        getGLtexMemory(tex, depth = 1) {
            let gl = this._gl;
            let channels = 0;
            let singlebyte = 0;
            let bytelength = 0;
            let srgb = this._sRGB ? this._sRGB.SRGB_EXT : gl.RGB;
            let srgb_alpha = this._sRGB ? this._sRGB.SRGB_ALPHA_EXT : gl.RGBA;
            switch (tex.internalFormat) {
                case gl.ALPHA:
                    channels = 1;
                    break;
                case srgb:
                case gl.RGB:
                    channels = 3;
                    break;
                case srgb_alpha:
                case gl.RGBA:
                    channels = 4;
                    break;
                default:
                    channels = 0;
                    break;
            }
            switch (tex.type) {
                case gl.UNSIGNED_BYTE:
                    singlebyte = 1;
                    break;
                case gl.UNSIGNED_SHORT_5_6_5:
                    singlebyte = 2 / 3;
                    break;
                case gl.FLOAT:
                    singlebyte = 4;
                    break;
                case this._oesTextureHalfFloat.HALF_FLOAT_OES:
                    singlebyte = 2;
                    break;
                default:
                    singlebyte = 0;
                    break;
            }
            bytelength = channels * singlebyte * tex.width * tex.height;
            if (tex.mipmap) {
                bytelength *= 1.333;
            }
            if (tex.target == gl.TEXTURE_CUBE_MAP)
                bytelength *= 6;
            else if (tex.target == gl.TEXTURE_2D)
                bytelength *= 1;
            return bytelength;
        }
        getGLRTTexMemory(width, height, colorFormat, depthStencilFormat, generateMipmap, multiSamples, cube) {
            let getpixelbyte = (rtFormat) => {
                let pixelByte = 0;
                switch (rtFormat) {
                    case Laya.RenderTargetFormat.R8G8B8:
                        pixelByte = 3;
                        break;
                    case Laya.RenderTargetFormat.R8G8B8A8:
                        pixelByte = 4;
                        break;
                    case Laya.RenderTargetFormat.R16G16B16A16:
                        pixelByte = 8;
                        break;
                    case Laya.RenderTargetFormat.R32G32B32:
                        pixelByte = 12;
                        break;
                    case Laya.RenderTargetFormat.R32G32B32A32:
                        pixelByte = 16;
                        break;
                    case Laya.RenderTargetFormat.R16G16B16:
                        pixelByte = 6;
                        break;
                    case Laya.RenderTargetFormat.DEPTH_16:
                        pixelByte = 2;
                        break;
                    case Laya.RenderTargetFormat.STENCIL_8:
                        pixelByte = 1;
                        break;
                    case Laya.RenderTargetFormat.DEPTHSTENCIL_24_8:
                        pixelByte = 4;
                        break;
                    case Laya.RenderTargetFormat.DEPTH_32:
                        pixelByte = 4;
                        break;
                }
                return pixelByte;
            };
            let colorPixelbyte = getpixelbyte(colorFormat);
            let depthPixelbyte = getpixelbyte(depthStencilFormat);
            if (multiSamples > 1)
                colorPixelbyte *= 2;
            if (cube)
                colorPixelbyte *= 6;
            if (generateMipmap)
                colorPixelbyte *= 1.333;
            let colorMemory = colorPixelbyte * width * height;
            let depthMemory = depthPixelbyte * width * height;
            return colorMemory + depthMemory;
        }
        supportSRGB(format, mipmap) {
            switch (format) {
                case Laya.TextureFormat.R8G8B8:
                case Laya.TextureFormat.R8G8B8A8:
                    return this._engine.getCapable(Laya.RenderCapable.Texture_SRGB) && !mipmap;
                case Laya.TextureFormat.DXT1:
                case Laya.TextureFormat.DXT3:
                case Laya.TextureFormat.DXT5:
                    return this._engine.getCapable(Laya.RenderCapable.COMPRESS_TEXTURE_S3TC_SRGB) && !mipmap;
                default:
                    return false;
            }
        }
        supportGenerateMipmap(format) {
            switch (format) {
                case Laya.RenderTargetFormat.DEPTH_16:
                case Laya.RenderTargetFormat.DEPTHSTENCIL_24_8:
                case Laya.RenderTargetFormat.DEPTH_32:
                case Laya.RenderTargetFormat.STENCIL_8:
                    return false;
                default:
                    return true;
            }
        }
        isSRGBFormat(format) {
            switch (format) {
                case Laya.TextureFormat.ETC2SRGB:
                case Laya.TextureFormat.ETC2SRGB_Alpha8:
                case Laya.TextureFormat.ETC2SRGB_Alpha1:
                case Laya.TextureFormat.ASTC4x4SRGB:
                case Laya.TextureFormat.ASTC6x6SRGB:
                case Laya.TextureFormat.ASTC8x8SRGB:
                case Laya.TextureFormat.ASTC10x10SRGB:
                case Laya.TextureFormat.ASTC12x12SRGB:
                    return true;
                default:
                    return false;
            }
        }
        createTextureInternal(dimension, width, height, format, generateMipmap, sRGB, premultipliedAlpha) {
            let useSRGBExt = this.isSRGBFormat(format) || (sRGB && this.supportSRGB(format, generateMipmap));
            if (premultipliedAlpha) {
                useSRGBExt = false;
            }
            let gammaCorrection = 1.0;
            if (!useSRGBExt && sRGB) {
                gammaCorrection = 2.2;
            }
            let target = this.getTarget(dimension);
            let internalTex = new WebGLInternalTex(this._engine, target, width, height, 1, dimension, generateMipmap, useSRGBExt, gammaCorrection);
            let glParam = this.glTextureParam(format, useSRGBExt);
            internalTex.internalFormat = glParam.internalFormat;
            internalTex.format = glParam.format;
            internalTex.type = glParam.type;
            return internalTex;
        }
        setTextureImageData(texture, source, premultiplyAlpha, invertY) {
            if (texture.width != source.width || texture.height != source.height) {
                console.warn("setTextureImageData: size not match");
            }
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            texture.width;
            texture.height;
            let gl = texture._gl;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texImage2D(target, 0, internalFormat, format, type, source);
            texture.gpuMemory = this.getGLtexMemory(texture);
            if (texture.mipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        }
        setTextureSubImageData(texture, source, x, y, premultiplyAlpha, invertY) {
            let target = texture.target;
            texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            source.width;
            source.height;
            let gl = texture._gl;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texSubImage2D(target, 0, x, y, format, type, source);
            texture.gpuMemory = this.getGLtexMemory(texture);
            if (texture.mipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        }
        initVideoTextureData(texture) {
            let target = texture.target;
            texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let width = texture.width;
            let height = texture.height;
            let gl = texture._gl;
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texImage2D(target, 0, texture.internalFormat, width, height, 0, format, type, null);
            texture.gpuMemory = this.getGLtexMemory(texture);
            if (texture.mipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
        }
        setTexturePixelsData(texture, source, premultiplyAlpha, invertY) {
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let width = texture.width;
            let height = texture.height;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            let gl = texture._gl;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texImage2D(target, 0, internalFormat, width, height, 0, format, type, source);
            texture.gpuMemory = this.getGLtexMemory(texture);
            if (texture.mipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setTextureSubPixelsData(texture, source, mipmapLevel, generateMipmap, xOffset, yOffset, width, height, premultiplyAlpha, invertY) {
            generateMipmap = generateMipmap && mipmapLevel == 0;
            let target = texture.target;
            texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            let gl = texture._gl;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texSubImage2D(target, mipmapLevel, xOffset, yOffset, width, height, format, type, source);
            if (texture.mipmap && generateMipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setTextureDDSData(texture, ddsInfo) {
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let width = texture.width;
            let height = texture.height;
            let source = ddsInfo.source;
            let dataOffset = ddsInfo.dataOffset;
            let bpp = ddsInfo.bpp;
            let blockBytes = ddsInfo.blockBytes;
            let mipmapCount = ddsInfo.mipmapCount;
            let compressed = ddsInfo.compressed;
            texture.maxMipmapLevel = mipmapCount - 1;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            let gl = texture._gl;
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            let formatParams = this.getFormatPixelsParams(ddsInfo.format);
            let channelsByte = formatParams.bytesPerPixel / formatParams.channels;
            let dataTypeConstur = formatParams.dataTypedCons;
            let mipmapWidth = width;
            let mipmapHeight = height;
            let memory = 0;
            for (let index = 0; index < mipmapCount; index++) {
                if (compressed) {
                    let dataLength = (((Math.max(4, mipmapWidth) / 4) * Math.max(4, mipmapHeight)) / 4) * blockBytes;
                    let sourceData = new Uint8Array(source, dataOffset, dataLength);
                    gl.compressedTexImage2D(target, index, internalFormat, mipmapWidth, mipmapHeight, 0, sourceData);
                    memory += sourceData.byteLength;
                    dataOffset += bpp ? (mipmapWidth * mipmapHeight * (bpp / 8)) : dataLength;
                }
                else {
                    let dataLength = mipmapWidth * mipmapHeight * formatParams.channels;
                    let sourceData = new dataTypeConstur(source, dataOffset, dataLength);
                    memory += sourceData.byteLength;
                    gl.texImage2D(target, index, internalFormat, mipmapWidth, mipmapHeight, 0, format, type, sourceData);
                    dataOffset += dataLength * channelsByte;
                }
                mipmapWidth *= 0.5;
                mipmapHeight *= 0.5;
                mipmapWidth = Math.max(1.0, mipmapWidth);
                mipmapHeight = Math.max(1.0, mipmapHeight);
            }
            texture.gpuMemory = memory;
            this._engine._bindTexture(texture.target, null);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setTextureKTXData(texture, ktxInfo) {
            let source = ktxInfo.source;
            let compressed = ktxInfo.compress;
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let mipmapCount = texture.mipmapCount;
            let width = texture.width;
            let height = texture.height;
            texture.maxMipmapLevel = mipmapCount - 1;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            let gl = texture._gl;
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            let mipmapWidth = width;
            let mipmapHeight = height;
            let dataOffset = ktxInfo.headerOffset + ktxInfo.bytesOfKeyValueData;
            let memory = 0;
            for (let index = 0; index < ktxInfo.mipmapCount; index++) {
                let imageSize = new Int32Array(source, dataOffset, 1)[0];
                dataOffset += 4;
                if (compressed) {
                    let sourceData = new Uint8Array(source, dataOffset, imageSize);
                    gl.compressedTexImage2D(target, index, internalFormat, mipmapWidth, mipmapHeight, 0, sourceData);
                    memory += sourceData.byteLength;
                }
                else {
                    let pixelParams = this.getFormatPixelsParams(ktxInfo.format);
                    let typedSize = imageSize / pixelParams.typedSize;
                    let sourceData = new pixelParams.dataTypedCons(source, dataOffset, typedSize);
                    gl.texImage2D(target, index, internalFormat, mipmapWidth, mipmapHeight, 0, format, type, sourceData);
                    memory += sourceData.byteLength;
                }
                dataOffset += imageSize;
                dataOffset += 3 - ((imageSize + 3) % 4);
                mipmapWidth = Math.max(1, mipmapWidth * 0.5);
                mipmapHeight = Math.max(1, mipmapHeight * 0.5);
            }
            for (let index = ktxInfo.mipmapCount; index < texture.mipmapCount; index++) {
                if (compressed) ;
                else {
                    gl.texImage2D(target, index, internalFormat, mipmapWidth, mipmapHeight, 0, format, type, null);
                }
                mipmapWidth = Math.max(1, mipmapWidth * 0.5);
                mipmapHeight = Math.max(1, mipmapHeight * 0.5);
            }
            texture.gpuMemory = memory;
            this._engine._bindTexture(texture.target, null);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setTextureHDRData(texture, hdrInfo) {
            let hdrPixelData = hdrInfo.readScanLine();
            this.setTexturePixelsData(texture, hdrPixelData, false, false);
        }
        setCubeImageData(texture, sources, premultiplyAlpha, invertY) {
            let gl = texture._gl;
            const cubeFace = [
                gl.TEXTURE_CUBE_MAP_POSITIVE_Z,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Z,
                gl.TEXTURE_CUBE_MAP_POSITIVE_X,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_X,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Y,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Y,
            ];
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            texture.width;
            texture.height;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            this._engine._bindTexture(texture.target, texture.resource);
            for (let index = 0; index < cubeFace.length; index++) {
                let target = cubeFace[index];
                gl.texImage2D(target, 0, internalFormat, format, type, sources[index]);
            }
            if (texture.mipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
            texture.gpuMemory = this.getGLtexMemory(texture);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        }
        setCubePixelsData(texture, source, premultiplyAlpha, invertY) {
            let gl = texture._gl;
            const cubeFace = [
                gl.TEXTURE_CUBE_MAP_POSITIVE_Z,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Z,
                gl.TEXTURE_CUBE_MAP_POSITIVE_X,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_X,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Y,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Y,
            ];
            texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let width = texture.width;
            let height = texture.height;
            let fourSize = width % 4 == 0;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            if (source) {
                for (let index = 0; index < cubeFace.length; index++) {
                    let t = cubeFace[index];
                    gl.texImage2D(t, 0, internalFormat, width, height, 0, format, type, source[index]);
                }
                if (texture.mipmap) {
                    gl.generateMipmap(texture.target);
                }
            }
            else {
                for (let index = 0; index < cubeFace.length; index++) {
                    let t = cubeFace[index];
                    gl.texImage2D(t, 0, internalFormat, width, height, 0, format, type, null);
                }
                if (texture.mipmap) {
                    gl.generateMipmap(texture.target);
                }
            }
            this._engine._bindTexture(texture.target, null);
            texture.gpuMemory = this.getGLtexMemory(texture);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setCubeSubPixelData(texture, source, mipmapLevel, generateMipmap, xOffset, yOffset, width, height, premultiplyAlpha, invertY) {
            generateMipmap = generateMipmap && mipmapLevel == 0;
            let gl = texture._gl;
            const cubeFace = [
                gl.TEXTURE_CUBE_MAP_POSITIVE_Z,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Z,
                gl.TEXTURE_CUBE_MAP_POSITIVE_X,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_X,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Y,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Y,
            ];
            texture.target;
            texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let fourSize = width % 4 == 0;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            for (let index = 0; index < cubeFace.length; index++) {
                let target = cubeFace[index];
                gl.texSubImage2D(target, mipmapLevel, xOffset, yOffset, width, height, format, type, source[index]);
            }
            if (texture.mipmap && generateMipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setCubeDDSData(texture, ddsInfo) {
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let width = texture.width;
            let height = texture.height;
            let source = ddsInfo.source;
            let dataOffset = ddsInfo.dataOffset;
            let bpp = ddsInfo.bpp;
            let blockBytes = ddsInfo.blockBytes;
            let mipmapCount = ddsInfo.mipmapCount;
            texture.maxMipmapLevel = mipmapCount - 1;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            fourSize = true;
            let gl = texture._gl;
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            const cubeFace = [
                gl.TEXTURE_CUBE_MAP_POSITIVE_X,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_X,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Y,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Y,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Z,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Z,
            ];
            let formatParams = this.getFormatPixelsParams(ddsInfo.format);
            let channelsByte = formatParams.bytesPerPixel / formatParams.channels;
            let dataTypeConstur = formatParams.dataTypedCons;
            let memory = 0;
            if (!ddsInfo.compressed) {
                for (let face = 0; face < 6; face++) {
                    let target = cubeFace[face];
                    let mipmapWidth = width;
                    let mipmapHeight = height;
                    for (let index = 0; index < mipmapCount; index++) {
                        let dataLength = mipmapWidth * mipmapHeight * formatParams.channels;
                        let sourceData = new dataTypeConstur(source, dataOffset, dataLength);
                        gl.texImage2D(target, index, internalFormat, mipmapWidth, mipmapHeight, 0, format, type, sourceData);
                        memory += sourceData.byteLength;
                        dataOffset += dataLength * channelsByte;
                        mipmapWidth *= 0.5;
                        mipmapHeight *= 0.5;
                        mipmapWidth = Math.max(1.0, mipmapWidth);
                        mipmapHeight = Math.max(1.0, mipmapHeight);
                    }
                }
            }
            else {
                for (let face = 0; face < 6; face++) {
                    let target = cubeFace[face];
                    let mipmapWidth = width;
                    let mipmapHeight = height;
                    for (let index = 0; index < mipmapCount; index++) {
                        let dataLength = Math.max(4, mipmapWidth) / 4 * Math.max(4, mipmapHeight) / 4 * blockBytes;
                        let sourceData = new Uint8Array(source, dataOffset, dataLength);
                        (texture.mipmap || index == 0) && gl.compressedTexImage2D(target, index, internalFormat, mipmapWidth, mipmapHeight, 0, sourceData);
                        memory += sourceData.byteLength;
                        dataOffset += bpp ? (mipmapWidth * mipmapHeight * (bpp / 8)) : dataLength;
                        mipmapWidth *= 0.5;
                        mipmapHeight *= 0.5;
                        mipmapWidth = Math.max(1.0, mipmapWidth);
                        mipmapHeight = Math.max(1.0, mipmapHeight);
                    }
                }
            }
            texture.gpuMemory = memory;
            this._engine._bindTexture(texture.target, null);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setCubeKTXData(texture, ktxInfo) {
            let source = ktxInfo.source;
            let compressed = ktxInfo.compress;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let mipmapCount = ktxInfo.mipmapCount;
            let width = texture.width;
            let height = texture.height;
            texture.maxMipmapLevel = mipmapCount - 1;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            let gl = texture._gl;
            const cubeFace = [
                gl.TEXTURE_CUBE_MAP_POSITIVE_X,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_X,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Y,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Y,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Z,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Z,
            ];
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            let mipmapWidth = width;
            let mipmapHeight = height;
            let dataOffset = ktxInfo.headerOffset + ktxInfo.bytesOfKeyValueData;
            let memory = 0;
            for (let index = 0; index < ktxInfo.mipmapCount; index++) {
                let imageSize = new Int32Array(source, dataOffset, 1)[0];
                dataOffset += 4;
                for (let face = 0; face < 6; face++) {
                    let target = cubeFace[face];
                    if (compressed) {
                        let sourceData = new Uint8Array(source, dataOffset, imageSize);
                        gl.compressedTexImage2D(target, index, internalFormat, mipmapWidth, mipmapHeight, 0, sourceData);
                        memory += sourceData.byteLength;
                    }
                    else {
                        let pixelParams = this.getFormatPixelsParams(ktxInfo.format);
                        let typedSize = imageSize / pixelParams.typedSize;
                        let sourceData = new pixelParams.dataTypedCons(source, dataOffset, typedSize);
                        gl.texImage2D(target, index, internalFormat, mipmapWidth, mipmapHeight, 0, format, type, sourceData);
                        memory += sourceData.byteLength;
                    }
                    dataOffset += imageSize;
                    dataOffset += 3 - ((imageSize + 3) % 4);
                }
                mipmapWidth = Math.max(1, mipmapWidth * 0.5);
                mipmapHeight = Math.max(1, mipmapHeight * 0.5);
            }
            for (let index = ktxInfo.mipmapCount; index < texture.mipmapCount; index++) {
                for (let face = 0; face < 6; face++) {
                    let target = cubeFace[face];
                    if (compressed) ;
                    else {
                        gl.texImage2D(target, index, internalFormat, mipmapWidth, mipmapHeight, 0, format, type, null);
                    }
                }
                mipmapWidth = Math.max(1, mipmapWidth * 0.5);
                mipmapHeight = Math.max(1, mipmapHeight * 0.5);
            }
            this._engine._bindTexture(texture.target, null);
            texture.gpuMemory = memory;
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setTextureCompareMode(texture, compareMode) {
            return Laya.TextureCompareMode.None;
        }
        bindRenderTarget(renderTarget, faceIndex = 0) {
            this.currentActiveRT && this.unbindRenderTarget(this.currentActiveRT);
            let gl = this._gl;
            let framebuffer = renderTarget._framebuffer;
            gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
            if (renderTarget._isCube) {
                let texture = renderTarget._textures[0];
                gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_CUBE_MAP_POSITIVE_X + faceIndex, texture.resource, 0);
            }
            this.currentActiveRT = renderTarget;
        }
        bindoutScreenTarget() {
            if (this.currentActiveRT != WebGLEngine._lastFrameBuffer) {
                this.unbindRenderTarget(this.currentActiveRT);
            }
        }
        unbindRenderTarget(renderTarget) {
            let gl = renderTarget._gl;
            if (renderTarget && renderTarget._generateMipmap) {
                renderTarget._textures.forEach(tex => {
                    let target = tex.target;
                    this._engine._bindTexture(target, tex.resource);
                    gl.generateMipmap(target);
                    this._engine._bindTexture(target, null);
                });
            }
            gl.bindFramebuffer(gl.FRAMEBUFFER, WebGLEngine._lastFrameBuffer_WebGLOBJ);
            this.currentActiveRT = WebGLEngine._lastFrameBuffer;
        }
        createRenderTextureCubeInternal(dimension, size, format, generateMipmap, sRGB) {
            let useSRGBExt = false;
            generateMipmap = generateMipmap && this.supportGenerateMipmap(format);
            let gammaCorrection = 1.0;
            let target = this.getTarget(dimension);
            let internalTex = new WebGLInternalTex(this._engine, target, size, size, 1, dimension, generateMipmap, useSRGBExt, gammaCorrection);
            let glParam = this.glRenderTextureParam(format, useSRGBExt);
            internalTex.internalFormat = glParam.internalFormat;
            internalTex.format = glParam.format;
            internalTex.type = glParam.type;
            let internalFormat = internalTex.internalFormat;
            let glFormat = internalTex.format;
            let type = internalTex.type;
            let gl = internalTex._gl;
            const cubeFace = [
                gl.TEXTURE_CUBE_MAP_POSITIVE_Z,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Z,
                gl.TEXTURE_CUBE_MAP_POSITIVE_X,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_X,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Y,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Y,
            ];
            this._engine._bindTexture(internalTex.target, internalTex.resource);
            for (let index = 0; index < cubeFace.length; index++) {
                let target = cubeFace[index];
                gl.texImage2D(target, 0, internalFormat, size, size, 0, glFormat, type, null);
            }
            this._engine._bindTexture(internalTex.target, null);
            if (format == Laya.RenderTargetFormat.DEPTH_16 || format == Laya.RenderTargetFormat.DEPTH_32 || format == Laya.RenderTargetFormat.DEPTHSTENCIL_24_8) {
                internalTex.filterMode = Laya.FilterMode.Point;
            }
            return internalTex;
        }
        createRenderTargetInternal(width, height, colorFormat, depthStencilFormat, generateMipmap, sRGB, multiSamples, storage) {
            multiSamples = 1;
            let texture = this.createRenderTextureInternal(Laya.TextureDimension.Tex2D, width, height, colorFormat, generateMipmap, sRGB);
            let renderTarget = new WebGLInternalRT(this._engine, colorFormat, depthStencilFormat, false, texture.mipmap, multiSamples);
            renderTarget.gpuMemory = this.getGLRTTexMemory(width, height, colorFormat, depthStencilFormat, generateMipmap, multiSamples, false);
            renderTarget.colorFormat = colorFormat;
            renderTarget.depthStencilFormat = depthStencilFormat;
            renderTarget._textures.push(texture);
            let framebuffer = renderTarget._framebuffer;
            let gl = renderTarget._gl;
            gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
            let colorAttachment = this.glRenderTargetAttachment(colorFormat);
            gl.framebufferTexture2D(gl.FRAMEBUFFER, colorAttachment, gl.TEXTURE_2D, texture.resource, 0);
            let depthBufferParam = this.glRenderBufferParam(depthStencilFormat, false);
            if (depthBufferParam) {
                let depthbuffer = this.createRenderbuffer(width, height, depthBufferParam.internalFormat, renderTarget._samples);
                renderTarget._depthbuffer = depthbuffer;
                gl.framebufferRenderbuffer(gl.FRAMEBUFFER, depthBufferParam.attachment, gl.RENDERBUFFER, depthbuffer);
            }
            gl.bindFramebuffer(gl.FRAMEBUFFER, WebGLEngine._lastFrameBuffer_WebGLOBJ);
            return renderTarget;
        }
        createRenderTargetCubeInternal(size, colorFormat, depthStencilFormat, generateMipmap, sRGB, multiSamples) {
            multiSamples = 1;
            let texture = this.createRenderTextureCubeInternal(Laya.TextureDimension.Cube, size, colorFormat, generateMipmap, sRGB);
            let renderTarget = new WebGLInternalRT(this._engine, colorFormat, depthStencilFormat, true, texture.mipmap, multiSamples);
            renderTarget.gpuMemory = this.getGLRTTexMemory(size, size, colorFormat, depthStencilFormat, generateMipmap, multiSamples, true);
            renderTarget._textures.push(texture);
            let framebuffer = renderTarget._framebuffer;
            let gl = renderTarget._gl;
            gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
            let depthBufferParam = this.glRenderBufferParam(depthStencilFormat, false);
            if (depthBufferParam) {
                let depthbuffer = this.createRenderbuffer(size, size, depthBufferParam.internalFormat, renderTarget._samples);
                renderTarget._depthbuffer = depthbuffer;
                gl.framebufferRenderbuffer(gl.FRAMEBUFFER, depthBufferParam.attachment, gl.RENDERBUFFER, depthbuffer);
            }
            gl.bindFramebuffer(gl.FRAMEBUFFER, WebGLEngine._lastFrameBuffer_WebGLOBJ);
            return renderTarget;
        }
        createRenderbuffer(width, height, internalFormat, samples) {
            let gl = this._gl;
            let renderbuffer = gl.createRenderbuffer();
            gl.bindRenderbuffer(gl.RENDERBUFFER, renderbuffer);
            gl.renderbufferStorage(gl.RENDERBUFFER, internalFormat, width, height);
            gl.bindRenderbuffer(gl.RENDERBUFFER, null);
            return renderbuffer;
        }
        createRenderTextureInternal(dimension, width, height, format, generateMipmap, sRGB) {
            let useSRGBExt = false;
            generateMipmap = generateMipmap && this.supportGenerateMipmap(format);
            let gammaCorrection = 1.0;
            let target = this.getTarget(dimension);
            let internalTex = new WebGLInternalTex(this._engine, target, width, height, 1, dimension, generateMipmap, useSRGBExt, gammaCorrection);
            let glParam = this.glRenderTextureParam(format, useSRGBExt);
            internalTex.internalFormat = glParam.internalFormat;
            internalTex.format = glParam.format;
            internalTex.type = glParam.type;
            let internalFormat = internalTex.internalFormat;
            let glFormat = internalTex.format;
            let type = internalTex.type;
            let gl = internalTex._gl;
            this._engine._bindTexture(internalTex.target, internalTex.resource);
            gl.texImage2D(target, 0, internalFormat, width, height, 0, glFormat, type, null);
            this._engine._bindTexture(internalTex.target, null);
            if (format == Laya.RenderTargetFormat.DEPTH_16 || format == Laya.RenderTargetFormat.DEPTH_32 || format == Laya.RenderTargetFormat.DEPTHSTENCIL_24_8) {
                internalTex.filterMode = Laya.FilterMode.Point;
            }
            return internalTex;
        }
        createRenderTargetDepthTexture(renderTarget, dimension, width, height) {
            let gl = renderTarget._gl;
            if (renderTarget.depthStencilFormat == Laya.RenderTargetFormat.None) {
                return null;
            }
            let depthbuffer = renderTarget._depthbuffer;
            depthbuffer && gl.deleteRenderbuffer(depthbuffer);
            renderTarget._depthbuffer = null;
            let format = renderTarget.depthStencilFormat;
            let mipmap = renderTarget._generateMipmap;
            let sRGB = renderTarget.isSRGB;
            if (renderTarget._depthTexture) {
                gl.deleteTexture(renderTarget._depthTexture);
            }
            let texture = this.createRenderTextureInternal(dimension, width, height, format, mipmap, sRGB);
            renderTarget._depthTexture = texture;
            let attachment = this.glRenderTargetAttachment(renderTarget.depthStencilFormat);
            let framebuffer = renderTarget._framebuffer;
            gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
            gl.framebufferTexture2D(gl.FRAMEBUFFER, attachment, gl.TEXTURE_2D, texture.resource, 0);
            gl.bindFramebuffer(gl.FRAMEBUFFER, WebGLEngine._lastFrameBuffer_WebGLOBJ);
            return texture;
        }
        readRenderTargetPixelData(renderTarget, xOffset, yOffset, width, height, out) {
            let gl = renderTarget._gl;
            this.bindRenderTarget(renderTarget);
            let frameState = gl.checkFramebufferStatus(gl.FRAMEBUFFER) == gl.FRAMEBUFFER_COMPLETE;
            if (!frameState) {
                this.unbindRenderTarget(renderTarget);
                return null;
            }
            switch (renderTarget.colorFormat) {
                case Laya.RenderTargetFormat.R8G8B8:
                    gl.readPixels(xOffset, yOffset, width, height, gl.RGB, gl.UNSIGNED_BYTE, out);
                    break;
                case Laya.RenderTargetFormat.R8G8B8A8:
                    gl.readPixels(xOffset, yOffset, width, height, gl.RGBA, gl.UNSIGNED_BYTE, out);
                    break;
                case Laya.RenderTargetFormat.R16G16B16:
                    gl.readPixels(xOffset, yOffset, width, height, gl.RGB, gl.FLOAT, out);
                    break;
                case Laya.RenderTargetFormat.R16G16B16A16:
                    gl.readPixels(xOffset, yOffset, width, height, gl.RGBA, gl.FLOAT, out);
                    break;
                case Laya.RenderTargetFormat.R32G32B32:
                    gl.readPixels(xOffset, yOffset, width, height, gl.RGB, gl.FLOAT, out);
                    break;
                case Laya.RenderTargetFormat.R32G32B32A32:
                    gl.readPixels(xOffset, yOffset, width, height, gl.RGBA, gl.FLOAT, out);
                    break;
            }
            this.unbindRenderTarget(renderTarget);
            return out;
        }
        readRenderTargetPixelDataAsync(renderTarget, xOffset, yOffset, width, height, out) {
            return Promise.resolve(this.readRenderTargetPixelData(renderTarget, xOffset, yOffset, width, height, out));
        }
        updateVideoTexture(texture, video, premultiplyAlpha, invertY) {
            let gl = texture._gl;
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            texture.width;
            texture.height;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texImage2D(target, 0, internalFormat, format, type, video);
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
    }

    class GL2TextureContext extends GLTextureContext {
        constructor(engine) {
            super(engine);
        }
        getTarget(dimension) {
            let target = -1;
            switch (dimension) {
                case Laya.TextureDimension.Cube:
                    target = this._gl.TEXTURE_CUBE_MAP;
                    break;
                case Laya.TextureDimension.Tex2D:
                    target = this._gl.TEXTURE_2D;
                    break;
                case Laya.TextureDimension.Texture2DArray:
                    target = this._gl.TEXTURE_2D_ARRAY;
                    break;
                case Laya.TextureDimension.Tex3D:
                    target = this._gl.TEXTURE_3D;
                    break;
                default:
                    throw "Unknow Texture Target";
            }
            return target;
        }
        glTextureParam(format, useSRGB) {
            let gl = this._gl;
            this._glParam.internalFormat = null;
            this._glParam.format = null;
            this._glParam.type = null;
            switch (format) {
                case Laya.TextureFormat.Alpha8:
                    this._glParam.internalFormat = gl.R8;
                    this._glParam.format = gl.RED;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.R8G8B8:
                    this._glParam.internalFormat = useSRGB ? gl.SRGB8 : gl.RGB8;
                    this._glParam.format = gl.RGB;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.R8G8B8A8:
                    this._glParam.internalFormat = useSRGB ? gl.SRGB8_ALPHA8 : gl.RGBA8;
                    this._glParam.format = gl.RGBA;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.TextureFormat.R5G6B5:
                    this._glParam.internalFormat = gl.RGB565;
                    this._glParam.format = gl.RGB;
                    this._glParam.type = gl.UNSIGNED_SHORT_5_6_5;
                    break;
                case Laya.TextureFormat.R32G32B32A32:
                    this._glParam.internalFormat = gl.RGBA32F;
                    this._glParam.format = gl.RGBA;
                    this._glParam.type = gl.FLOAT;
                    break;
                case Laya.TextureFormat.R32G32B32:
                    this._glParam.internalFormat = gl.RGB32F;
                    this._glParam.format = gl.RGB;
                    this._glParam.type = gl.FLOAT;
                    break;
                case Laya.TextureFormat.R16G16B16:
                    this._glParam.internalFormat = gl.RGB16F;
                    this._glParam.format = gl.RGB;
                    this._glParam.type = gl.HALF_FLOAT;
                    break;
                case Laya.TextureFormat.R16G16B16A16:
                    this._glParam.internalFormat = gl.RGBA16F;
                    this._glParam.format = gl.RGBA;
                    this._glParam.type = gl.HALF_FLOAT;
                    break;
                case Laya.TextureFormat.DXT1:
                    this._glParam.internalFormat = useSRGB ? this._compressdTextureS3tc_srgb.COMPRESSED_SRGB_ALPHA_S3TC_DXT1_EXT : this._compressedTextureS3tc.COMPRESSED_RGBA_S3TC_DXT1_EXT;
                    break;
                case Laya.TextureFormat.DXT3:
                    this._glParam.internalFormat = useSRGB ? this._compressdTextureS3tc_srgb.COMPRESSED_SRGB_ALPHA_S3TC_DXT3_EXT : this._compressedTextureS3tc.COMPRESSED_RGBA_S3TC_DXT3_EXT;
                    break;
                case Laya.TextureFormat.DXT5:
                    this._glParam.internalFormat = useSRGB ? this._compressdTextureS3tc_srgb.COMPRESSED_SRGB_ALPHA_S3TC_DXT5_EXT : this._compressedTextureS3tc.COMPRESSED_RGBA_S3TC_DXT5_EXT;
                    break;
                case Laya.TextureFormat.ETC1RGB:
                    this._glParam.internalFormat = this._compressedTextureEtc1.COMPRESSED_RGB_ETC1_WEBGL;
                    break;
                case Laya.TextureFormat.ETC2RGBA:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_RGBA8_ETC2_EAC;
                    break;
                case Laya.TextureFormat.ETC2RGB:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_RGB8_ETC2;
                    break;
                case Laya.TextureFormat.ETC2SRGB:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_SRGB8_ETC2;
                    break;
                case Laya.TextureFormat.ETC2SRGB_Alpha8:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_SRGB8_ALPHA8_ETC2_EAC;
                    break;
                case Laya.TextureFormat.ETC2RGB_Alpha1:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_RGB8_PUNCHTHROUGH_ALPHA1_ETC2;
                    break;
                case Laya.TextureFormat.ETC2SRGB_Alpha1:
                    this._glParam.internalFormat = this._compressedTextureETC.COMPRESSED_SRGB8_PUNCHTHROUGH_ALPHA1_ETC2;
                    break;
                case Laya.TextureFormat.ASTC4x4:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_RGBA_ASTC_4x4_KHR;
                    break;
                case Laya.TextureFormat.ASTC6x6:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_RGBA_ASTC_6x6_KHR;
                    break;
                case Laya.TextureFormat.ASTC8x8:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_RGBA_ASTC_8x8_KHR;
                    break;
                case Laya.TextureFormat.ASTC10x10:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_RGBA_ASTC_10x10_KHR;
                    break;
                case Laya.TextureFormat.ASTC12x12:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_RGBA_ASTC_12x12_KHR;
                    break;
                case Laya.TextureFormat.ASTC4x4SRGB:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_SRGB8_ALPHA8_ASTC_4x4_KHR;
                    break;
                case Laya.TextureFormat.ASTC6x6SRGB:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_SRGB8_ALPHA8_ASTC_6x6_KHR;
                    break;
                case Laya.TextureFormat.ASTC8x8SRGB:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_SRGB8_ALPHA8_ASTC_8x8_KHR;
                    break;
                case Laya.TextureFormat.ASTC10x10SRGB:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_SRGB8_ALPHA8_ASTC_10x10_KHR;
                    break;
                case Laya.TextureFormat.ASTC12x12SRGB:
                    this._glParam.internalFormat = this._compressedTextureASTC.COMPRESSED_SRGB8_ALPHA8_ASTC_12x12_KHR;
                    break;
                default:
                    throw "Unknown Texture Format.";
            }
            return this._glParam;
        }
        glRenderBufferParam(format, useSRGB) {
            let gl = this._gl;
            switch (format) {
                case Laya.RenderTargetFormat.DEPTH_16:
                    return { internalFormat: gl.DEPTH_COMPONENT16, attachment: gl.DEPTH_ATTACHMENT };
                case Laya.RenderTargetFormat.DEPTHSTENCIL_24_8:
                    return { internalFormat: gl.DEPTH24_STENCIL8, attachment: gl.DEPTH_STENCIL_ATTACHMENT };
                case Laya.RenderTargetFormat.DEPTH_32:
                    return { internalFormat: gl.DEPTH_COMPONENT32F, attachment: gl.DEPTH_ATTACHMENT };
                case Laya.RenderTargetFormat.STENCIL_8:
                    return { internalFormat: gl.STENCIL_INDEX8, attachment: gl.STENCIL_ATTACHMENT };
                case Laya.RenderTargetFormat.R8G8B8:
                    return { internalFormat: useSRGB ? gl.SRGB8 : gl.RGB8, attachment: gl.COLOR_ATTACHMENT0 };
                case Laya.RenderTargetFormat.R8G8B8A8:
                    return { internalFormat: useSRGB ? gl.SRGB8_ALPHA8 : gl.RGBA8, attachment: gl.COLOR_ATTACHMENT0 };
                case Laya.RenderTargetFormat.R16G16B16:
                    return { internalFormat: gl.RGB16F, attachment: gl.COLOR_ATTACHMENT0 };
                case Laya.RenderTargetFormat.R16G16B16A16:
                    return { internalFormat: gl.RGBA16F, attachment: gl.COLOR_ATTACHMENT0 };
                case Laya.RenderTargetFormat.R32G32B32:
                    return { internalFormat: gl.RGB32F, attachment: gl.COLOR_ATTACHMENT0 };
                case Laya.RenderTargetFormat.R32G32B32A32:
                    return { internalFormat: gl.RGBA32F, attachment: gl.COLOR_ATTACHMENT0 };
                default:
                    return null;
            }
        }
        glRenderTextureParam(format, useSRGB) {
            let gl = this._gl;
            this._glParam.internalFormat = null;
            this._glParam.format = null;
            this._glParam.type = null;
            switch (format) {
                case Laya.RenderTargetFormat.R8G8B8:
                    this._glParam.internalFormat = useSRGB ? gl.SRGB8 : gl.RGB8;
                    this._glParam.format = gl.RGB;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.RenderTargetFormat.R8G8B8A8:
                    this._glParam.internalFormat = useSRGB ? gl.SRGB8_ALPHA8 : gl.RGBA8;
                    this._glParam.format = gl.RGBA;
                    this._glParam.type = gl.UNSIGNED_BYTE;
                    break;
                case Laya.RenderTargetFormat.R16G16B16:
                    this._glParam.internalFormat = gl.RGB16F;
                    this._glParam.format = gl.RGB;
                    this._glParam.type = gl.HALF_FLOAT;
                    break;
                case Laya.RenderTargetFormat.R16G16B16A16:
                    this._glParam.internalFormat = gl.RGBA16F;
                    this._glParam.format = gl.RGBA;
                    this._glParam.type = gl.HALF_FLOAT;
                    break;
                case Laya.RenderTargetFormat.R32G32B32:
                    this._glParam.internalFormat = gl.RGB32F;
                    this._glParam.format = gl.RGB;
                    this._glParam.type = gl.FLOAT;
                    break;
                case Laya.RenderTargetFormat.R32G32B32A32:
                    this._glParam.internalFormat = gl.RGBA32F;
                    this._glParam.format = gl.RGBA;
                    this._glParam.type = gl.FLOAT;
                    break;
                case Laya.RenderTargetFormat.DEPTH_16:
                    this._glParam.internalFormat = gl.DEPTH_COMPONENT16;
                    this._glParam.format = gl.DEPTH_COMPONENT;
                    this._glParam.type = gl.UNSIGNED_INT;
                    break;
                case Laya.RenderTargetFormat.DEPTHSTENCIL_24_8:
                    this._glParam.internalFormat = gl.DEPTH24_STENCIL8;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_INT_24_8;
                    break;
                case Laya.RenderTargetFormat.DEPTH_32:
                    this._glParam.internalFormat = gl.DEPTH_COMPONENT32F;
                    this._glParam.format = this._glParam.internalFormat;
                    this._glParam.type = gl.UNSIGNED_INT;
                    break;
                case Laya.RenderTargetFormat.STENCIL_8:
                    break;
                default:
                    throw "depth texture format wrong.";
            }
            return this._glParam;
        }
        getGLtexMemory(tex, depth = 1) {
            let gl = this._gl;
            let channels = 0;
            let singlebyte = 0;
            let bytelength = 0;
            switch (tex.internalFormat) {
                case gl.R8:
                case gl.ALPHA:
                    channels = 1;
                    break;
                case gl.SRGB8:
                case gl.RGB8:
                case gl.RGB565:
                case gl.RGB32F:
                case gl.RGB16F:
                    channels = 3;
                    break;
                case gl.SRGB8_ALPHA8:
                case gl.RGBA8:
                case gl.RGBA32F:
                case gl.RGBA16F:
                    channels = 4;
                    break;
                default:
                    channels = 0;
                    break;
            }
            switch (tex.type) {
                case gl.UNSIGNED_BYTE:
                    singlebyte = 1;
                    break;
                case gl.UNSIGNED_SHORT_5_6_5:
                    singlebyte = 2 / 3;
                    break;
                case gl.FLOAT:
                    singlebyte = 4;
                    break;
                case gl.HALF_FLOAT:
                    singlebyte = 2;
                    break;
                default:
                    singlebyte = 0;
                    break;
            }
            bytelength = channels * singlebyte * tex.width * tex.height;
            if (tex.mipmap) {
                bytelength *= 1.333;
            }
            if (tex.target == gl.TEXTURE_CUBE_MAP)
                bytelength *= 6;
            else if (tex.target == gl.TEXTURE_2D)
                bytelength *= 1;
            else if (tex.target == gl.TEXTURE_2D_ARRAY)
                bytelength *= depth;
            return bytelength;
        }
        supportSRGB(format, mipmap) {
            switch (format) {
                case Laya.TextureFormat.R8G8B8:
                    return this._engine.getCapable(Laya.RenderCapable.Texture_SRGB) && !mipmap;
                case Laya.TextureFormat.R8G8B8A8:
                    return this._engine.getCapable(Laya.RenderCapable.Texture_SRGB);
                case Laya.TextureFormat.DXT1:
                case Laya.TextureFormat.DXT3:
                case Laya.TextureFormat.DXT5:
                    return this._engine.getCapable(Laya.RenderCapable.COMPRESS_TEXTURE_S3TC_SRGB) && !mipmap;
                default:
                    return false;
            }
        }
        setTextureImageData(texture, source, premultiplyAlpha, invertY) {
            if (texture.width != source.width || texture.height != source.height) {
                console.warn("setTextureImageData: size not match");
            }
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let width = texture.width;
            let height = texture.height;
            let mipmapCount = texture.mipmapCount;
            let gl = this._gl;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texStorage2D(target, mipmapCount, internalFormat, width, height);
            gl.texSubImage2D(target, 0, 0, 0, width, height, format, type, source);
            texture.gpuMemory = this.getGLtexMemory(texture);
            if (texture.mipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        }
        setTextureSubImageData(texture, source, x, y, premultiplyAlpha, invertY) {
            let target = texture.target;
            texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            texture.width;
            texture.height;
            texture.mipmapCount;
            let gl = this._gl;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texSubImage2D(target, 0, x, y, source.width, source.height, format, type, source);
            texture.gpuMemory = this.getGLtexMemory(texture);
            if (texture.mipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        }
        setTexturePixelsData(texture, source, premultiplyAlpha, invertY) {
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let width = texture.width;
            let height = texture.height;
            let mipmapCount = texture.mipmapCount;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            let gl = this._gl;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texStorage2D(target, mipmapCount, internalFormat, width, height);
            texture.gpuMemory = this.getGLtexMemory(texture);
            if (source) {
                gl.texSubImage2D(target, 0, 0, 0, width, height, format, type, source);
                if (texture.mipmap) {
                    gl.generateMipmap(texture.target);
                }
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        createTexture3DInternal(dimension, width, height, depth, format, generateMipmap, sRGB, premultipliedAlpha) {
            let useSRGBExt = this.isSRGBFormat(format) || (sRGB && this.supportSRGB(format, generateMipmap));
            if (premultipliedAlpha) {
                useSRGBExt = false;
            }
            let gammaCorrection = 1.0;
            if (!useSRGBExt && sRGB) {
                gammaCorrection = 2.2;
            }
            let target = this.getTarget(dimension);
            let internalTex = new WebGLInternalTex(this._engine, target, width, height, depth, dimension, generateMipmap, useSRGBExt, gammaCorrection);
            let glParam = this.glTextureParam(format, useSRGBExt);
            internalTex.internalFormat = glParam.internalFormat;
            internalTex.format = glParam.format;
            internalTex.type = glParam.type;
            return internalTex;
        }
        setTexture3DImageData(texture, sources, depth, premultiplyAlpha, invertY) {
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let width = texture.width;
            let height = texture.height;
            let mipmapCount = texture.mipmapCount;
            let gl = this._gl;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texStorage3D(target, mipmapCount, internalFormat, width, height, depth);
            texture.gpuMemory = this.getGLtexMemory(texture, depth);
            for (let index = 0; index < depth; index++) {
                gl.texSubImage3D(target, 0, 0, 0, index, width, height, 1, format, type, sources[index]);
            }
            texture.gpuMemory = this.getGLtexMemory(texture);
            if (texture.mipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        }
        setTexture3DPixelsData(texture, source, depth, premultiplyAlpha, invertY) {
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let width = texture.width;
            let height = texture.height;
            let mipmapCount = texture.mipmapCount;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            let gl = this._gl;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texStorage3D(target, mipmapCount, internalFormat, width, height, depth);
            texture.gpuMemory = this.getGLtexMemory(texture, depth);
            if (source) {
                gl.texSubImage3D(target, 0, 0, 0, 0, width, height, depth, format, type, source);
                if (texture.mipmap) {
                    gl.generateMipmap(texture.target);
                }
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setTexture3DSubPixelsData(texture, source, mipmapLevel, generateMipmap, xOffset, yOffset, zOffset, width, height, depth, premultiplyAlpha, invertY) {
            generateMipmap = generateMipmap && mipmapLevel == 0;
            let target = texture.target;
            texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            let gl = this._gl;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texSubImage3D(target, mipmapLevel, xOffset, yOffset, zOffset, width, height, depth, format, type, source);
            if (texture.mipmap && generateMipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setTextureHDRData(texture, hdrInfo) {
            let sourceData = hdrInfo.readScanLine();
            this.setTexturePixelsData(texture, sourceData, false, false);
        }
        setTextureKTXData(texture, ktxInfo) {
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let mipmapCount = texture.mipmapCount;
            let width = texture.width;
            let height = texture.height;
            texture.maxMipmapLevel = mipmapCount - 1;
            let source = ktxInfo.source;
            let compressed = ktxInfo.compress;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            let gl = this._gl;
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            if (!compressed) {
                gl.texStorage2D(target, ktxInfo.mipmapCount, internalFormat, width, height);
            }
            let mipmapWidth = width;
            let mipmapHeight = height;
            let dataOffset = ktxInfo.headerOffset + ktxInfo.bytesOfKeyValueData;
            let memory = 0;
            for (let index = 0; index < ktxInfo.mipmapCount; index++) {
                let imageSize = new Int32Array(source, dataOffset, 1)[0];
                dataOffset += 4;
                if (compressed) {
                    let sourceData = new Uint8Array(source, dataOffset, imageSize);
                    gl.compressedTexImage2D(target, index, internalFormat, mipmapWidth, mipmapHeight, 0, sourceData);
                    memory += sourceData.byteLength;
                }
                else {
                    let pixelParams = this.getFormatPixelsParams(ktxInfo.format);
                    let typedSize = imageSize / pixelParams.typedSize;
                    let sourceData = new pixelParams.dataTypedCons(source, dataOffset, typedSize);
                    gl.texSubImage2D(target, index, 0, 0, mipmapWidth, mipmapHeight, format, type, sourceData);
                    memory += sourceData.byteLength;
                }
                dataOffset += imageSize;
                dataOffset += 3 - ((imageSize + 3) % 4);
                mipmapWidth = Math.max(1, mipmapWidth * 0.5);
                mipmapHeight = Math.max(1, mipmapHeight * 0.5);
            }
            this._engine._bindTexture(texture.target, null);
            texture.gpuMemory = memory;
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setCubeImageData(texture, sources, premultiplyAlpha, invertY) {
            let gl = this._gl;
            const cubeFace = [
                gl.TEXTURE_CUBE_MAP_POSITIVE_Z,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Z,
                gl.TEXTURE_CUBE_MAP_POSITIVE_X,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_X,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Y,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Y,
            ];
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let width = texture.width;
            let height = texture.height;
            let mipmapCount = texture.mipmapCount;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texStorage2D(target, mipmapCount, internalFormat, width, height);
            texture.gpuMemory = this.getGLtexMemory(texture);
            for (let index = 0; index < cubeFace.length; index++) {
                let t = cubeFace[index];
                gl.texSubImage2D(t, 0, 0, 0, format, type, sources[index]);
            }
            if (texture.mipmap) {
                gl.generateMipmap(texture.target);
            }
            this._engine._bindTexture(texture.target, null);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        }
        setCubePixelsData(texture, source, premultiplyAlpha, invertY) {
            let gl = this._gl;
            const cubeFace = [
                gl.TEXTURE_CUBE_MAP_POSITIVE_Z,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Z,
                gl.TEXTURE_CUBE_MAP_POSITIVE_X,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_X,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Y,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Y,
            ];
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let width = texture.width;
            let height = texture.height;
            let mipmapCount = texture.mipmapCount;
            let fourSize = width % 4 == 0;
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            gl.texStorage2D(target, mipmapCount, internalFormat, width, height);
            if (source) {
                for (let index = 0; index < cubeFace.length; index++) {
                    let t = cubeFace[index];
                    gl.texSubImage2D(t, 0, 0, 0, width, height, format, type, source[index]);
                }
                if (texture.mipmap) {
                    gl.generateMipmap(texture.target);
                }
            }
            this._engine._bindTexture(texture.target, null);
            texture.gpuMemory = this.getGLtexMemory(texture);
            premultiplyAlpha && gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            invertY && gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setCubeKTXData(texture, ktxInfo) {
            let gl = this._gl;
            const cubeFace = [
                gl.TEXTURE_CUBE_MAP_POSITIVE_X,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_X,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Y,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Y,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Z,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Z,
            ];
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            texture.mipmapCount;
            let width = texture.width;
            let height = texture.height;
            texture.maxMipmapLevel = ktxInfo.mipmapCount - 1;
            let source = ktxInfo.source;
            let compressed = ktxInfo.compress;
            let mipmapWidth = width;
            let mipmapHeight = height;
            let dataOffset = ktxInfo.headerOffset + ktxInfo.bytesOfKeyValueData;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            if (!compressed) {
                gl.texStorage2D(target, ktxInfo.mipmapCount, internalFormat, width, height);
            }
            let memory = 0;
            for (let index = 0; index < ktxInfo.mipmapCount; index++) {
                let imageSize = new Int32Array(source, dataOffset, 1)[0];
                dataOffset += 4;
                for (let face = 0; face < 6; face++) {
                    let t = cubeFace[face];
                    if (compressed) {
                        let sourceData = new Uint8Array(source, dataOffset, imageSize);
                        gl.compressedTexImage2D(t, index, internalFormat, mipmapWidth, mipmapHeight, 0, sourceData);
                        memory += sourceData.byteLength;
                    }
                    else {
                        let pixelParams = this.getFormatPixelsParams(ktxInfo.format);
                        let typedSize = imageSize / pixelParams.typedSize;
                        let sourceData = new pixelParams.dataTypedCons(source, dataOffset, typedSize);
                        gl.texSubImage2D(t, index, 0, 0, mipmapWidth, mipmapHeight, format, type, sourceData);
                        memory += sourceData.byteLength;
                    }
                    dataOffset += imageSize;
                    dataOffset += 3 - ((imageSize + 3) % 4);
                }
                mipmapWidth = Math.max(1, mipmapWidth * 0.5);
                mipmapHeight = Math.max(1, mipmapHeight * 0.5);
            }
            texture.gpuMemory = memory;
            this._engine._bindTexture(texture.target, null);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        getCubeKTXRGBMData(texture, ktxInfo) {
            let gl = this._gl;
            const cubeFace = [
                gl.TEXTURE_CUBE_MAP_POSITIVE_X,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_X,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Y,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Y,
                gl.TEXTURE_CUBE_MAP_POSITIVE_Z,
                gl.TEXTURE_CUBE_MAP_NEGATIVE_Z,
            ];
            let target = texture.target;
            let internalFormat = texture.internalFormat;
            let format = texture.format;
            let type = texture.type;
            let mipmapCount = texture.mipmapCount;
            let width = texture.width;
            let height = texture.height;
            texture.maxMipmapLevel = mipmapCount - 1;
            let source = ktxInfo.source;
            let compressed = ktxInfo.compress;
            let mipmapWidth = width;
            let mipmapHeight = height;
            let dataOffset = ktxInfo.headerOffset + ktxInfo.bytesOfKeyValueData;
            let fourSize = width % 4 == 0 && height % 4 == 0;
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            this._engine._bindTexture(texture.target, texture.resource);
            if (!compressed) {
                gl.texStorage2D(target, ktxInfo.mipmapCount, internalFormat, width, height);
            }
            let memory = 0;
            for (let index = 0; index < ktxInfo.mipmapCount; index++) {
                let imageSize = new Int32Array(source, dataOffset, 1)[0];
                dataOffset += 4;
                for (let face = 0; face < 6; face++) {
                    let t = cubeFace[face];
                    let pixelParams = this.getFormatPixelsParams(ktxInfo.format);
                    let typedSize = imageSize / pixelParams.typedSize;
                    let sourceData = new pixelParams.dataTypedCons(source, dataOffset, typedSize);
                    gl.texSubImage2D(t, index, 0, 0, mipmapWidth, mipmapHeight, format, type, sourceData);
                    memory += sourceData.byteLength;
                }
                dataOffset += imageSize;
                dataOffset += 3 - ((imageSize + 3) % 4);
            }
            mipmapWidth = Math.max(1, mipmapWidth * 0.5);
            mipmapHeight = Math.max(1, mipmapHeight * 0.5);
            texture.gpuMemory = memory;
            this._engine._bindTexture(texture.target, null);
            fourSize || gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
        }
        setTextureCompareMode(texture, compareMode) {
            let gl = this._gl;
            switch (compareMode) {
                case Laya.TextureCompareMode.LEQUAL:
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_FUNC, gl.LEQUAL);
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_MODE, gl.COMPARE_REF_TO_TEXTURE);
                    break;
                case Laya.TextureCompareMode.GEQUAL:
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_FUNC, gl.GEQUAL);
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_MODE, gl.COMPARE_REF_TO_TEXTURE);
                    break;
                case Laya.TextureCompareMode.LESS:
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_FUNC, gl.LESS);
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_MODE, gl.COMPARE_REF_TO_TEXTURE);
                    break;
                case Laya.TextureCompareMode.GREATER:
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_FUNC, gl.GREATER);
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_MODE, gl.COMPARE_REF_TO_TEXTURE);
                    break;
                case Laya.TextureCompareMode.EQUAL:
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_FUNC, gl.EQUAL);
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_MODE, gl.COMPARE_REF_TO_TEXTURE);
                    break;
                case Laya.TextureCompareMode.NOTEQUAL:
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_FUNC, gl.NOTEQUAL);
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_MODE, gl.COMPARE_REF_TO_TEXTURE);
                    break;
                case Laya.TextureCompareMode.ALWAYS:
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_FUNC, gl.ALWAYS);
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_MODE, gl.COMPARE_REF_TO_TEXTURE);
                    break;
                case Laya.TextureCompareMode.NEVER:
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_FUNC, gl.NEVER);
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_MODE, gl.COMPARE_REF_TO_TEXTURE);
                    break;
                case Laya.TextureCompareMode.None:
                default:
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_FUNC, gl.LEQUAL);
                    texture._setTexParameteri(gl.TEXTURE_COMPARE_MODE, gl.NONE);
                    break;
            }
            return compareMode;
        }
        createRenderbuffer(width, height, internalFormat, samples) {
            let gl = this._gl;
            let renderbuffer = gl.createRenderbuffer();
            gl.bindRenderbuffer(gl.RENDERBUFFER, renderbuffer);
            if (samples > 1) {
                gl.renderbufferStorageMultisample(gl.RENDERBUFFER, samples, internalFormat, width, height);
            }
            else {
                gl.renderbufferStorage(gl.RENDERBUFFER, internalFormat, width, height);
            }
            gl.bindRenderbuffer(gl.RENDERBUFFER, null);
            return renderbuffer;
        }
        createRenderTextureInternal(dimension, width, height, format, generateMipmap, sRGB) {
            generateMipmap = generateMipmap && this.supportGenerateMipmap(format);
            let useSRGBExt = this.isSRGBFormat(format) || (sRGB && this.supportSRGB(format, generateMipmap));
            let gammaCorrection = 1.0;
            let target = this.getTarget(dimension);
            let internalTex = new WebGLInternalTex(this._engine, target, width, height, 1, dimension, generateMipmap, useSRGBExt, gammaCorrection);
            let glParam = this.glRenderTextureParam(format, useSRGBExt);
            internalTex.internalFormat = glParam.internalFormat;
            internalTex.format = glParam.format;
            internalTex.type = glParam.type;
            let internalFormat = internalTex.internalFormat;
            internalTex.format;
            internalTex.type;
            let gl = this._gl;
            this._engine._bindTexture(internalTex.target, internalTex.resource);
            gl.texStorage2D(target, internalTex.mipmapCount, internalFormat, width, height);
            this._engine._bindTexture(internalTex.target, null);
            if (format == Laya.RenderTargetFormat.DEPTH_16 || format == Laya.RenderTargetFormat.DEPTH_32 || format == Laya.RenderTargetFormat.DEPTHSTENCIL_24_8) {
                internalTex.filterMode = Laya.FilterMode.Point;
            }
            return internalTex;
        }
        createRenderTargetInternal(width, height, colorFormat, depthStencilFormat, generateMipmap, sRGB, multiSamples, storage) {
            let texture = this.createRenderTextureInternal(Laya.TextureDimension.Tex2D, width, height, colorFormat, generateMipmap, sRGB);
            let renderTarget = new WebGLInternalRT(this._engine, colorFormat, depthStencilFormat, false, texture.mipmap, multiSamples);
            renderTarget.gpuMemory = this.getGLRTTexMemory(width, height, colorFormat, depthStencilFormat, generateMipmap, multiSamples, false);
            renderTarget._textures.push(texture);
            let gl = renderTarget._gl;
            if (renderTarget._samples > 1) {
                let msaaFramebuffer = renderTarget._msaaFramebuffer;
                let renderbufferParam = this.glRenderBufferParam(colorFormat, sRGB);
                let msaaRenderbuffer = renderTarget._msaaRenderbuffer = this.createRenderbuffer(width, height, renderbufferParam.internalFormat, renderTarget._samples);
                gl.bindFramebuffer(gl.FRAMEBUFFER, msaaFramebuffer);
                gl.framebufferRenderbuffer(gl.FRAMEBUFFER, renderbufferParam.attachment, gl.RENDERBUFFER, msaaRenderbuffer);
                let depthBufferParam = this.glRenderBufferParam(depthStencilFormat, false);
                if (depthBufferParam) {
                    let depthbuffer = this.createRenderbuffer(width, height, depthBufferParam.internalFormat, renderTarget._samples);
                    renderTarget._depthbuffer = depthbuffer;
                    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, depthBufferParam.attachment, gl.RENDERBUFFER, depthbuffer);
                }
                gl.bindFramebuffer(gl.FRAMEBUFFER, WebGLEngine._lastFrameBuffer_WebGLOBJ);
                let framebuffer = renderTarget._framebuffer;
                gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
                let colorAttachment = this.glRenderTargetAttachment(colorFormat);
                gl.framebufferTexture2D(gl.FRAMEBUFFER, colorAttachment, gl.TEXTURE_2D, texture.resource, 0);
                gl.bindFramebuffer(gl.FRAMEBUFFER, WebGLEngine._lastFrameBuffer_WebGLOBJ);
            }
            else {
                let framebuffer = renderTarget._framebuffer;
                gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
                let colorAttachment = this.glRenderTargetAttachment(colorFormat);
                gl.framebufferTexture2D(gl.FRAMEBUFFER, colorAttachment, gl.TEXTURE_2D, texture.resource, 0);
                let depthBufferParam = this.glRenderBufferParam(depthStencilFormat, false);
                if (depthBufferParam) {
                    let depthbuffer = this.createRenderbuffer(width, height, depthBufferParam.internalFormat, renderTarget._samples);
                    renderTarget._depthbuffer = depthbuffer;
                    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, depthBufferParam.attachment, gl.RENDERBUFFER, depthbuffer);
                }
                gl.bindFramebuffer(gl.FRAMEBUFFER, WebGLEngine._lastFrameBuffer_WebGLOBJ);
            }
            return renderTarget;
        }
        createRenderTargetCubeInternal(size, colorFormat, depthStencilFormat, generateMipmap, sRGB, multiSamples) {
            let texture = this.createRenderTextureCubeInternal(Laya.TextureDimension.Cube, size, colorFormat, generateMipmap, sRGB);
            let renderTarget = new WebGLInternalRT(this._engine, colorFormat, depthStencilFormat, true, texture.mipmap, multiSamples);
            renderTarget.gpuMemory = this.getGLRTTexMemory(size, size, colorFormat, depthStencilFormat, generateMipmap, multiSamples, true);
            renderTarget.colorFormat = colorFormat;
            renderTarget.depthStencilFormat = depthStencilFormat;
            renderTarget._textures.push(texture);
            renderTarget.isSRGB = sRGB;
            let gl = renderTarget._gl;
            if (renderTarget._samples > 1) {
                let msaaFramebuffer = renderTarget._msaaFramebuffer;
                let renderbufferParam = this.glRenderBufferParam(colorFormat, false);
                let msaaRenderbuffer = renderTarget._msaaRenderbuffer = this.createRenderbuffer(size, size, renderbufferParam.internalFormat, renderTarget._samples);
                gl.bindFramebuffer(gl.FRAMEBUFFER, msaaFramebuffer);
                gl.framebufferRenderbuffer(gl.FRAMEBUFFER, renderbufferParam.attachment, gl.RENDERBUFFER, msaaRenderbuffer);
                let depthBufferParam = this.glRenderBufferParam(depthStencilFormat, false);
                if (depthBufferParam) {
                    let depthbuffer = this.createRenderbuffer(size, size, depthBufferParam.internalFormat, renderTarget._samples);
                    renderTarget._depthbuffer = depthbuffer;
                    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, depthBufferParam.attachment, gl.RENDERBUFFER, depthbuffer);
                }
                gl.bindFramebuffer(gl.FRAMEBUFFER, WebGLEngine._lastFrameBuffer_WebGLOBJ);
            }
            else {
                let framebuffer = renderTarget._framebuffer;
                gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
                let depthBufferParam = this.glRenderBufferParam(depthStencilFormat, false);
                if (depthBufferParam) {
                    let depthbuffer = this.createRenderbuffer(size, size, depthBufferParam.internalFormat, renderTarget._samples);
                    renderTarget._depthbuffer = depthbuffer;
                    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, depthBufferParam.attachment, gl.RENDERBUFFER, depthbuffer);
                }
                gl.bindFramebuffer(gl.FRAMEBUFFER, WebGLEngine._lastFrameBuffer_WebGLOBJ);
            }
            return renderTarget;
        }
        createRenderTextureCubeInternal(dimension, size, format, generateMipmap, sRGB) {
            generateMipmap = generateMipmap && this.supportGenerateMipmap(format);
            let useSRGBExt = this.isSRGBFormat(format) || (sRGB && this.supportSRGB(format, generateMipmap));
            let gammaCorrection = 1.0;
            let target = this.getTarget(dimension);
            let internalTex = new WebGLInternalTex(this._engine, target, size, size, 1, dimension, generateMipmap, useSRGBExt, gammaCorrection);
            let glParam = this.glRenderTextureParam(format, useSRGBExt);
            internalTex.internalFormat = glParam.internalFormat;
            internalTex.format = glParam.format;
            internalTex.type = glParam.type;
            let internalFormat = internalTex.internalFormat;
            internalTex.format;
            internalTex.type;
            let gl = this._gl;
            this._engine._bindTexture(internalTex.target, internalTex.resource);
            gl.texStorage2D(target, internalTex.mipmapCount, internalFormat, size, size);
            this._engine._bindTexture(internalTex.target, null);
            return internalTex;
        }
        bindRenderTarget(renderTarget, faceIndex = 0) {
            this.currentActiveRT && this.unbindRenderTarget(this.currentActiveRT);
            let gl = this._gl;
            if (renderTarget._isCube) {
                let framebuffer = renderTarget._framebuffer;
                gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
                let texture = renderTarget._textures[0];
                gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_CUBE_MAP_POSITIVE_X + faceIndex, texture.resource, 0);
            }
            if (renderTarget._samples > 1) {
                gl.bindFramebuffer(gl.FRAMEBUFFER, renderTarget._msaaFramebuffer);
            }
            else {
                let framebuffer = renderTarget._framebuffer;
                gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
            }
            this.currentActiveRT = renderTarget;
        }
        unbindRenderTarget(renderTarget) {
            let gl = this._gl;
            if (renderTarget && renderTarget._samples > 1) {
                gl.bindFramebuffer(gl.READ_FRAMEBUFFER, renderTarget._msaaFramebuffer);
                gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, renderTarget._framebuffer);
                let texture = renderTarget._textures[0];
                let biltMask = gl.COLOR_BUFFER_BIT;
                if (renderTarget._depthTexture) {
                    biltMask |= gl.DEPTH_BUFFER_BIT;
                }
                gl.blitFramebuffer(0, 0, texture.width, texture.height, 0, 0, texture.width, texture.height, biltMask, gl.NEAREST);
            }
            if (renderTarget && renderTarget._generateMipmap) {
                renderTarget._textures.forEach(tex => {
                    let target = tex.target;
                    this._engine._bindTexture(target, tex.resource);
                    gl.generateMipmap(target);
                    this._engine._bindTexture(target, null);
                });
            }
            gl.bindFramebuffer(gl.FRAMEBUFFER, WebGLEngine._lastFrameBuffer_WebGLOBJ);
            this.currentActiveRT = WebGLEngine._lastFrameBuffer;
        }
    }

    class GLBuffer extends GLObject {
        constructor(engine, targetType, bufferUsageType) {
            super(engine);
            this._byteLength = 0;
            this._glTargetType = targetType;
            this._glBufferUsageType = bufferUsageType;
            this._getGLTarget(this._glTargetType);
            this._getGLUsage(this._glBufferUsageType);
            this._glBuffer = this._gl.createBuffer();
            switch (targetType) {
                case Laya.BufferTargetType.ARRAY_BUFFER:
                    this._statistics_M_Buffer = Laya.StatElement.M_VertexBuffer;
                    this._statistics_RC_Buffer = Laya.StatElement.C_VertexBuffer;
                    break;
                case Laya.BufferTargetType.ELEMENT_ARRAY_BUFFER:
                    this._statistics_M_Buffer = Laya.StatElement.M_IndexBuffer;
                    this._statistics_RC_Buffer = Laya.StatElement.C_IndexBuffer;
                    break;
                case Laya.BufferTargetType.UNIFORM_BUFFER:
                    this._statistics_M_Buffer = Laya.StatElement.M_UBOBuffer;
                    this._statistics_RC_Buffer = Laya.StatElement.C_UBOBuffer;
                    break;
            }
            Laya.LayaGL.statAgent.recordCountData(Laya.StatElement.C_GPUBuffer, 1);
            Laya.LayaGL.statAgent.recordCountData(this._statistics_RC_Buffer, 1);
        }
        _getGLUsage(usage) {
            switch (usage) {
                case Laya.BufferUsage.Static:
                    this._glUsage = this._gl.STATIC_DRAW;
                    break;
                case Laya.BufferUsage.Dynamic:
                    this._glUsage = this._gl.DYNAMIC_DRAW;
                    break;
                case Laya.BufferUsage.Stream:
                    this._glUsage = this._gl.STREAM_DRAW;
                    break;
                default:
                    console.error("usage is not standard");
                    break;
            }
        }
        _getGLTarget(target) {
            switch (target) {
                case Laya.BufferTargetType.ARRAY_BUFFER:
                    this._glTarget = this._gl.ARRAY_BUFFER;
                    break;
                case Laya.BufferTargetType.UNIFORM_BUFFER:
                    this._glTarget = this._gl.UNIFORM_BUFFER;
                    break;
                case Laya.BufferTargetType.ELEMENT_ARRAY_BUFFER:
                    this._glTarget = this._gl.ELEMENT_ARRAY_BUFFER;
                    break;
            }
        }
        _memorychange(bytelength) {
            Laya.LayaGL.statAgent.recordMemoryData(Laya.StatElement.M_GPUBuffer, -this._byteLength + bytelength);
            Laya.LayaGL.statAgent.recordMemoryData(Laya.StatElement.M_GPUMemory, -this._byteLength + bytelength);
            Laya.LayaGL.statAgent.recordMemoryData(this._statistics_M_Buffer, -this._byteLength + bytelength);
        }
        bindBuffer() {
            if (this._engine._getbindBuffer(this._glTargetType) != this) {
                this._gl.bindBuffer(this._glTarget, this._glBuffer);
                this._engine._setbindBuffer(this._glTargetType, this);
                return true;
            }
            return false;
        }
        unbindBuffer() {
            if (this._engine._getbindBuffer(this._glTargetType) == this) {
                this._gl.bindBuffer(this._glTarget, null);
                this._engine._setbindBuffer(this._glTargetType, null);
            }
        }
        orphanStorage() {
            this.bindBuffer();
            this.setDataLength(this._byteLength);
        }
        setDataLength(srcData) {
            let gl = this._gl;
            this.bindBuffer();
            this._memorychange(srcData);
            this._byteLength = srcData;
            gl.bufferData(this._glTarget, this._byteLength, this._glUsage);
            this.unbindBuffer();
        }
        setData(srcData, offset) {
            let gl = this._gl;
            this.bindBuffer();
            gl.bufferSubData(this._glTarget, offset, srcData);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_BufferUploadCount, 1);
            this.unbindBuffer();
        }
        setDataEx(srcData, offset, length) {
            let gl = this._gl;
            this.bindBuffer();
            gl.bufferSubData(this._glTarget, offset, srcData, 0, length);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_BufferUploadCount, 1);
            this.unbindBuffer();
        }
        bindBufferBase(glPointer) {
            const gl = this._gl;
            let bindInfo = this._engine._uboBindingMap[glPointer];
            if (bindInfo && bindInfo.buffer != this._glBuffer) {
                if (this._engine._getbindBuffer(this._glTargetType) != this) {
                    this._engine._setbindBuffer(this._glTargetType, this);
                }
                gl.bindBufferBase(this._glTarget, glPointer, this._glBuffer);
                bindInfo.buffer = this._glBuffer;
                bindInfo.offset = 0;
                bindInfo.size = this._byteLength;
            }
        }
        bindBufferRange(glPointer, offset, byteCount) {
            const gl = this._gl;
            let bindInfo = this._engine._uboBindingMap[glPointer];
            if (bindInfo) {
                if (bindInfo.buffer != this._glBuffer || bindInfo.offset != offset || bindInfo.size != byteCount) {
                    if (this._engine._getbindBuffer(this._glTargetType) != this) {
                        this._engine._setbindBuffer(this._glTargetType, this);
                    }
                    gl.bindBufferRange(this._glTarget, glPointer, this._glBuffer, offset, byteCount);
                    bindInfo.buffer = this._glBuffer;
                    bindInfo.offset = offset;
                    bindInfo.size = byteCount;
                }
            }
        }
        resizeBuffer(dataLength) {
            this.bindBuffer();
            const gl = this._gl;
            this._memorychange(dataLength);
            this._byteLength = dataLength;
            gl.bufferData(this._glTarget, this._byteLength, this._glUsage);
        }
        destroy() {
            super.destroy();
            const gl = this._gl;
            gl.deleteBuffer(this._glBuffer);
            this._memorychange(0);
            Laya.LayaGL.statAgent.recordCountData(Laya.StatElement.C_GPUBuffer, -1);
            Laya.LayaGL.statAgent.recordCountData(this._statistics_RC_Buffer, -1);
            this._byteLength = 0;
            this._engine = null;
            this._glBuffer = null;
            this._glTarget = null;
            this._glUsage = null;
            this._gl = null;
        }
    }

    exports.WebGLMode = void 0;
    (function (WebGLMode) {
        WebGLMode[WebGLMode["Auto"] = 0] = "Auto";
        WebGLMode[WebGLMode["WebGL2"] = 1] = "WebGL2";
        WebGLMode[WebGLMode["WebGL1"] = 2] = "WebGL1";
    })(exports.WebGLMode || (exports.WebGLMode = {}));

    class GLParams {
        constructor(engine) {
            this._engine = engine;
            this._gl = this._engine.gl;
            this._initParams();
        }
        _initParams() {
            const gl = this._gl;
            this._glParamsData = new Map();
            this._glParamsData.set(Laya.RenderParams.Max_Active_Texture_Count, gl.getParameter(gl.MAX_VERTEX_TEXTURE_IMAGE_UNITS));
            const maxVertexUniform = gl.getParameter(gl.MAX_VERTEX_UNIFORM_VECTORS);
            const maxFragUniform = gl.getParameter(gl.MAX_FRAGMENT_UNIFORM_VECTORS);
            this._glParamsData.set(Laya.RenderParams.Max_Uniform_Count, Math.min(maxVertexUniform, maxFragUniform));
            this._glParamsData.set(Laya.RenderParams.MAX_Texture_Size, gl.getParameter(gl.MAX_TEXTURE_SIZE));
            this._glParamsData.set(Laya.RenderParams.MAX_Texture_Image_Uint, gl.getParameter(gl.MAX_TEXTURE_IMAGE_UNITS));
            if (this._engine.getCapable(Laya.RenderCapable.Texture_anisotropic)) {
                const anisoExt = this._engine._supportCapatable.getExtension(exports.WebGLExtension.EXT_texture_filter_anisotropic);
                this._glParamsData.set(Laya.RenderParams.Max_AnisoLevel_Count, gl.getParameter(anisoExt.MAX_TEXTURE_MAX_ANISOTROPY_EXT));
            }
            if (this._engine.isWebGL2)
                this._glParamsData.set(Laya.RenderParams.SHADER_CAPAILITY_LEVEL, 35);
            else
                this._glParamsData.set(Laya.RenderParams.SHADER_CAPAILITY_LEVEL, 30);
            this._glParamsData.set(Laya.RenderParams.FLOAT, gl.FLOAT);
            this._glParamsData.set(Laya.RenderParams.UNSIGNED_BYTE, gl.UNSIGNED_BYTE);
            this._glParamsData.set(Laya.RenderParams.UNSIGNED_SHORT, gl.UNSIGNED_SHORT);
            this._glParamsData.set(Laya.RenderParams.BYTE, gl.BYTE);
        }
        getParams(params) {
            return this._glParamsData.get(params);
        }
    }

    class GLRenderDrawContext extends GLObject {
        constructor(engine) {
            super(engine);
            if (!this._engine.isWebGL2) {
                this._angleInstancedArrays = this._engine._supportCapatable.getExtension(exports.WebGLExtension.ANGLE_instanced_arrays);
            }
        }
        getMeshTopology(mode) {
            switch (mode) {
                case Laya.MeshTopology.Points:
                    return this._gl.POINTS;
                case Laya.MeshTopology.Lines:
                    return this._gl.LINES;
                case Laya.MeshTopology.LineLoop:
                    return this._gl.LINE_LOOP;
                case Laya.MeshTopology.LineStrip:
                    return this._gl.LINE_STRIP;
                case Laya.MeshTopology.Triangles:
                    return this._gl.TRIANGLES;
                case Laya.MeshTopology.TriangleStrip:
                    return this._gl.TRIANGLE_STRIP;
                case Laya.MeshTopology.TriangleFan:
                    return this._gl.TRIANGLE_FAN;
            }
        }
        getIndexType(type) {
            switch (type) {
                case Laya.IndexFormat.UInt8:
                    return this._gl.UNSIGNED_BYTE;
                case Laya.IndexFormat.UInt16:
                    return this._gl.UNSIGNED_SHORT;
                case Laya.IndexFormat.UInt32:
                    return this._gl.UNSIGNED_INT;
            }
        }
        drawElementsInstanced(mode, count, type, offset, instanceCount) {
            if (this._engine.isWebGL2)
                this._gl.drawElementsInstanced(mode, count, type, offset, instanceCount);
            else
                this._angleInstancedArrays.drawElementsInstancedANGLE(mode, count, type, offset, instanceCount);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_Triangle, count / 3 * instanceCount);
        }
        drawArraysInstanced(mode, first, count, instanceCount) {
            if (this._engine.isWebGL2)
                this._gl.drawArraysInstanced(mode, first, count, instanceCount);
            else
                this._angleInstancedArrays.drawArraysInstancedANGLE(mode, first, count, instanceCount);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_Triangle, (count - 2) * instanceCount);
        }
        drawArrays(mode, first, count) {
            this._gl.drawArrays(mode, first, count);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_Triangle, (count - 2));
        }
        drawElements(mode, count, type, offset) {
            this._gl.drawElements(mode, count, type, offset);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_Triangle, count / 3);
        }
        drawGeometryElement(geometryElement) {
            geometryElement.bufferState.bind();
            let element = geometryElement.drawParams.elements;
            let length = geometryElement.drawParams.length;
            switch (geometryElement.drawType) {
                case Laya.DrawType.DrawArray:
                    for (let i = 0; i < length; i += 2) {
                        this.drawArrays(geometryElement._glmode, element[i], element[i + 1]);
                    }
                    break;
                case Laya.DrawType.DrawElement:
                    for (let i = 0; i < length; i += 2) {
                        this.drawElements(geometryElement._glmode, element[i + 1], geometryElement._glindexFormat, element[i]);
                    }
                    break;
                case Laya.DrawType.DrawArrayInstance:
                    for (let i = 0; i < length; i += 2) {
                        this.drawArraysInstanced(geometryElement._glmode, element[i], element[i + 1], geometryElement.instanceCount);
                    }
                    Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_Instancing_DrawCall, length / 2);
                    break;
                case Laya.DrawType.DrawElementInstance:
                    for (let i = 0; i < length; i += 2) {
                        this.drawElementsInstanced(geometryElement._glmode, element[i + 1], geometryElement._glindexFormat, element[i], geometryElement.instanceCount);
                    }
                    Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_Instancing_DrawCall, length / 2);
                    break;
            }
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_DrawCall, length / 2);
        }
    }

    class GLRenderState {
        constructor(engine) {
            this._engine = engine;
            this._gl = this._engine.gl;
        }
        _initState() {
            this.setDepthFunc(Laya.CompareFunction.Less);
            this.setBlendEquationSeparate(Laya.BlendEquationSeparate.ADD, Laya.BlendEquationSeparate.ADD);
            this._blendEquation = Laya.BlendEquationSeparate.ADD;
            this._sFactor = Laya.BlendFactor.One;
            this._dFactor = Laya.BlendFactor.Zero;
            this._sFactorAlpha = Laya.BlendFactor.One;
            this._dFactorAlpha = Laya.BlendFactor.One;
        }
        _getBlendFactor(factor) {
            const gl = this._gl;
            switch (factor) {
                case Laya.BlendFactor.Zero:
                    return gl.ZERO;
                case Laya.BlendFactor.One:
                    return gl.ONE;
                case Laya.BlendFactor.SourceColor:
                    return gl.SRC_COLOR;
                case Laya.BlendFactor.OneMinusSourceColor:
                    return gl.ONE_MINUS_SRC_COLOR;
                case Laya.BlendFactor.DestinationColor:
                    return gl.DST_COLOR;
                case Laya.BlendFactor.OneMinusDestinationColor:
                    return gl.ONE_MINUS_DST_COLOR;
                case Laya.BlendFactor.SourceAlpha:
                    return gl.SRC_ALPHA;
                case Laya.BlendFactor.OneMinusSourceAlpha:
                    return gl.ONE_MINUS_SRC_ALPHA;
                case Laya.BlendFactor.DestinationAlpha:
                    return gl.DST_ALPHA;
                case Laya.BlendFactor.OneMinusDestinationAlpha:
                    return gl.ONE_MINUS_DST_ALPHA;
                case Laya.BlendFactor.SourceAlphaSaturate:
                    return gl.SRC_ALPHA_SATURATE;
                case Laya.BlendFactor.BlendColor:
                    return gl.CONSTANT_COLOR;
                case Laya.BlendFactor.OneMinusBlendColor:
                    return gl.ONE_MINUS_CONSTANT_COLOR;
            }
        }
        _getBlendOperation(factor) {
            const gl = this._gl;
            switch (factor) {
                case Laya.BlendEquationSeparate.ADD:
                    return gl.FUNC_ADD;
                case Laya.BlendEquationSeparate.SUBTRACT:
                    return gl.FUNC_SUBTRACT;
                case Laya.BlendEquationSeparate.REVERSE_SUBTRACT:
                    return gl.FUNC_REVERSE_SUBTRACT;
                default:
                    throw "Unknow type";
            }
        }
        _getGLCompareFunction(compareFunction) {
            const gl = this._gl;
            switch (compareFunction) {
                case Laya.CompareFunction.Never:
                    return gl.NEVER;
                case Laya.CompareFunction.Less:
                    return gl.LESS;
                case Laya.CompareFunction.Equal:
                    return gl.EQUAL;
                case Laya.CompareFunction.LessEqual:
                    return gl.LEQUAL;
                case Laya.CompareFunction.Greater:
                    return gl.GREATER;
                case Laya.CompareFunction.NotEqual:
                    return gl.NOTEQUAL;
                case Laya.CompareFunction.GreaterEqual:
                    return gl.GEQUAL;
                case Laya.CompareFunction.Always:
                    return gl.ALWAYS;
                default:
                    return gl.LEQUAL;
            }
        }
        _getGLStencilOperation(compareFunction) {
            const gl = this._gl;
            switch (compareFunction) {
                case Laya.StencilOperation.Keep:
                    return gl.KEEP;
                case Laya.StencilOperation.Zero:
                    return gl.ZERO;
                case Laya.StencilOperation.Replace:
                    return gl.REPLACE;
                case Laya.StencilOperation.IncrementSaturate:
                    return gl.INCR;
                case Laya.StencilOperation.DecrementSaturate:
                    return gl.DECR;
                case Laya.StencilOperation.Invert:
                    return gl.INVERT;
                case Laya.StencilOperation.IncrementWrap:
                    return gl.INCR_WRAP;
                case Laya.StencilOperation.DecrementWrap:
                    return gl.DECR_WRAP;
            }
        }
        _getGLFrontfaceFactor(cullmode) {
            if (cullmode == Laya.CullMode.Front)
                return this._gl.CCW;
            else
                return this._gl.CW;
        }
        setDepthTest(value) {
            value !== this._depthTest && (this._depthTest = value, value ? this._gl.enable(this._gl.DEPTH_TEST) : this._gl.disable(this._gl.DEPTH_TEST));
        }
        setDepthMask(value) {
            value !== this._depthMask && (this._depthMask = value, this._gl.depthMask(value));
        }
        setDepthFunc(value) {
            value !== this._depthFunc && (this._depthFunc = value, this._gl.depthFunc(this._getGLCompareFunction(value)));
        }
        setStencilTest(value) {
            value !== this._stencilTest && (this._stencilTest = value, value ? this._gl.enable(this._gl.STENCIL_TEST) : this._gl.disable(this._gl.STENCIL_TEST));
        }
        setStencilWrite(value) {
            this._stencilWrite = value;
        }
        setStencilWriteMask(mask) {
            mask = this._stencilWrite ? mask : 0x00;
            if (mask !== this._stencilWriteMask) {
                this._stencilWriteMask = mask;
                this._gl.stencilMask(mask);
            }
        }
        setStencilFunc(fun, ref, mask) {
            if (fun != this._stencilFunc || ref != this._stencilRef || mask != this._stencilReadMask) {
                this._stencilFunc = fun;
                this._stencilRef = ref;
                this._stencilReadMask = mask;
                this._gl.stencilFunc(this._getGLCompareFunction(fun), ref, mask);
            }
        }
        setStencilOp(fail, zfail, zpass) {
            if (this._stencilOp_fail != fail || this._stencilOp_zfail != zfail || this._stencilOp_zpass != zpass) {
                this._stencilOp_fail = fail;
                this._stencilOp_zfail = zfail;
                this._stencilOp_zpass = zpass;
                this._gl.stencilOp(this._getGLStencilOperation(fail), this._getGLStencilOperation(zfail), this._getGLStencilOperation(zpass));
            }
        }
        setDepthBias(value) {
            if (value !== this._depthBias) {
                this._depthBias = value;
                value ? this._gl.enable(this._gl.POLYGON_OFFSET_FILL) : this._gl.disable(this._gl.POLYGON_OFFSET_FILL);
            }
        }
        setDepthBiasFactor(constantFactor, slopeFactor, clamp = 0.0) {
            if (constantFactor !== this._depthBiasConstant || slopeFactor !== this._depthBiasSlope || clamp !== this._depthBiasClamp) {
                this._depthBiasConstant = constantFactor;
                this._depthBiasSlope = slopeFactor;
                this._depthBiasClamp = clamp;
                this._gl.polygonOffset(constantFactor, slopeFactor);
            }
        }
        setBlend(value) {
            value !== this._blend && (this._blend = value, value ? this._gl.enable(this._gl.BLEND) : this._gl.disable(this._gl.BLEND));
        }
        setBlendEquation(blendEquation) {
            if (blendEquation !== this._blendEquation) {
                this._blendEquation = blendEquation;
                this._blendEquationRGB = this._blendEquationAlpha = null;
                this._gl.blendEquation(this._getBlendOperation(blendEquation));
            }
        }
        setBlendEquationSeparate(blendEquationRGB, blendEquationAlpha) {
            if (blendEquationRGB !== this._blendEquationRGB || blendEquationAlpha !== this._blendEquationAlpha) {
                this._blendEquationRGB = blendEquationRGB;
                this._blendEquationAlpha = blendEquationAlpha;
                this._blendEquation = null;
                this._gl.blendEquationSeparate(this._getBlendOperation(blendEquationRGB), this._getBlendOperation(blendEquationAlpha));
            }
        }
        setBlendFunc(sFactor, dFactor, force = false) {
            if (force || sFactor !== this._sFactor || dFactor !== this._dFactor) {
                this._sFactor = sFactor;
                this._dFactor = dFactor;
                this._sFactorRGB = null;
                this._dFactorRGB = null;
                this._sFactorAlpha = null;
                this._dFactorAlpha = null;
                this._gl.blendFunc(this._getBlendFactor(sFactor), this._getBlendFactor(dFactor));
            }
        }
        setBlendFuncSeperate(srcRGB, dstRGB, srcAlpha, dstAlpha) {
            if (srcRGB !== this._sFactorRGB || dstRGB !== this._dFactorRGB || srcAlpha !== this._sFactorAlpha || dstAlpha !== this._dFactorAlpha) {
                this._sFactorRGB = srcRGB;
                this._dFactorRGB = dstRGB;
                this._sFactorAlpha = srcAlpha;
                this._dFactorAlpha = dstAlpha;
                this._sFactor = null;
                this._dFactor = null;
                this._gl.blendFuncSeparate(this._getBlendFactor(srcRGB), this._getBlendFactor(dstRGB), this._getBlendFactor(srcAlpha), this._getBlendFactor(dstAlpha));
            }
        }
        setCullFace(value) {
            value !== this._cullFace && (this._cullFace = value, value ? this._gl.enable(this._gl.CULL_FACE) : this._gl.disable(this._gl.CULL_FACE));
        }
        setFrontFace(value) {
            value !== this._frontFace && (this._frontFace = value, this._gl.frontFace(this._getGLFrontfaceFactor(value)));
        }
        clearRenderStateCache() {
            this.renderStateCache = null;
            this.isTargetCache = null;
            this.invertFrontCache = null;
        }
        setRenderState(renderState, isTarget, invertFront) {
            if (this.isTargetCache == isTarget && this.invertFrontCache == invertFront && this.renderStateCache === renderState.hash) {
                return;
            }
            let depthWrite = renderState.depthWrite;
            this.setDepthMask(depthWrite);
            let depthTest = renderState.depthTest;
            if (depthTest == Laya.RenderState.DEPTHTEST_OFF)
                this.setDepthTest(false);
            else {
                this.setDepthTest(true);
                this.setDepthFunc(depthTest);
            }
            let stencilWrite = renderState.stencilWrite;
            this.setStencilWrite(stencilWrite);
            let stencilWriteMask = renderState.stencilWriteMask;
            this.setStencilWriteMask(stencilWriteMask);
            let stencilOp = renderState.stencilOp;
            this.setStencilOp(stencilOp.x, stencilOp.y, stencilOp.z);
            let stencilTest = renderState.stencilTest;
            if (stencilTest == Laya.RenderState.STENCILTEST_OFF) {
                this.setStencilTest(false);
            }
            else {
                this.setStencilTest(true);
                let stencilRef = renderState.stencilRef;
                let stencilReadMask = renderState.stencilReadMask;
                this.setStencilFunc(stencilTest, stencilRef, stencilReadMask);
            }
            let depthBias = renderState.depthBias;
            this.setDepthBias(depthBias);
            if (depthBias) {
                let depthBiasConstant = renderState.depthBiasConstant;
                let depthBiasSlopeScale = renderState.depthBiasSlopeScale;
                let depthBiasClamp = renderState.depthBiasClamp;
                this.setDepthBiasFactor(depthBiasConstant, depthBiasSlopeScale, depthBiasClamp);
            }
            let blend = renderState.blend;
            switch (blend) {
                case Laya.RenderState.BLEND_DISABLE:
                    this.setBlend(false);
                    break;
                case Laya.RenderState.BLEND_ENABLE_ALL:
                    let blendEquation = renderState.blendEquation;
                    let srcBlend = renderState.srcBlend;
                    let dstBlend = renderState.dstBlend;
                    this.setBlend(true);
                    this.setBlendEquation(blendEquation);
                    this.setBlendFunc(srcBlend, dstBlend);
                    break;
                case Laya.RenderState.BLEND_ENABLE_SEPERATE:
                    let blendEquationRGB = renderState.blendEquationRGB;
                    let blendEquationAlpha = renderState.blendEquationAlpha;
                    let srcRGB = renderState.srcBlendRGB;
                    let dstRGB = renderState.dstBlendRGB;
                    let srcAlpha = renderState.srcBlendAlpha;
                    let dstAlpha = renderState.dstBlendAlpha;
                    this.setBlend(true);
                    this.setBlendEquationSeparate(blendEquationRGB, blendEquationAlpha);
                    this.setBlendFuncSeperate(srcRGB, dstRGB, srcAlpha, dstAlpha);
                    break;
            }
            let cull = renderState.cull;
            let forntFace;
            switch (cull) {
                case Laya.RenderState.CULL_NONE:
                    this.setCullFace(false);
                    if (isTarget != invertFront)
                        forntFace = Laya.CullMode.Front;
                    else
                        forntFace = Laya.CullMode.Back;
                    this.setFrontFace(forntFace);
                    break;
                case Laya.RenderState.CULL_FRONT:
                    this.setCullFace(true);
                    if (isTarget == invertFront)
                        forntFace = Laya.CullMode.Front;
                    else
                        forntFace = Laya.CullMode.Back;
                    this.setFrontFace(forntFace);
                    break;
                case Laya.RenderState.CULL_BACK:
                default:
                    this.setCullFace(true);
                    if (isTarget != invertFront)
                        forntFace = Laya.CullMode.Front;
                    else
                        forntFace = Laya.CullMode.Back;
                    this.setFrontFace(forntFace);
                    break;
            }
            this.renderStateCache = renderState.hash;
            this.isTargetCache = isTarget;
            this.invertFrontCache = invertFront;
        }
    }

    class GLShaderInstance extends GLObject {
        constructor(engine, vs, ps, attributeMap) {
            super(engine);
            this._vs = vs;
            this._ps = ps;
            this._attributeMap = attributeMap;
            this._uniformMap = [];
            this._create();
        }
        _create() {
            WebGLEngine._lastShaderError = null;
            performance.now();
            const gl = this._gl;
            if (WebGLEngine.instance.lost) {
                return;
            }
            let prog = this._program = gl.createProgram();
            let compileErr;
            this._vshader = this._createShader(gl, this._vs, gl.VERTEX_SHADER);
            if (!gl.getShaderParameter(this._vshader, gl.COMPILE_STATUS))
                compileErr = gl.getShaderInfoLog(this._vshader);
            this._pshader = this._createShader(gl, this._ps, gl.FRAGMENT_SHADER);
            if (!gl.getShaderParameter(this._pshader, gl.COMPILE_STATUS)) {
                if (compileErr)
                    compileErr += "\n";
                compileErr += gl.getShaderInfoLog(this._pshader);
            }
            gl.attachShader(prog, this._vshader);
            gl.attachShader(prog, this._pshader);
            if (compileErr) {
                WebGLEngine._lastShaderError = compileErr;
                return;
            }
            for (var k in this._attributeMap)
                gl.bindAttribLocation(prog, this._attributeMap[k][0], k);
            gl.linkProgram(prog);
            if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
                WebGLEngine._lastShaderError = gl.getProgramInfoLog(prog);
                return;
            }
            const nUniformNum = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
            this.useProgram();
            this._curActTexIndex = 0;
            let one, i;
            for (i = 0; i < nUniformNum; i++) {
                var uniformData = gl.getActiveUniform(prog, i);
                var uniName = uniformData.name;
                let location = gl.getUniformLocation(prog, uniName);
                if (!location && location != 0)
                    continue;
                one = new Laya.ShaderVariable();
                one.location = location;
                if (uniName.indexOf('[0]') > 0) {
                    one.name = uniName = uniName.substr(0, uniName.length - 3);
                    one.isArray = true;
                }
                else {
                    one.name = uniName;
                    one.isArray = false;
                }
                one.type = uniformData.type;
                this._addShaderUnifiormFun(one);
                this._uniformMap.push(one);
                one.dataOffset = this._engine.propertyNameToID(uniName);
            }
            if (this._engine.isWebGL2) {
                const gl2 = gl;
                this._uniformObjectMap = {};
                var nUniformBlock = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORM_BLOCKS);
                for (i = 0; i < nUniformBlock; i++) {
                    var uniformBlockName = gl2.getActiveUniformBlockName(this._program, i);
                    one = new Laya.ShaderVariable();
                    one.name = uniformBlockName;
                    one.isArray = false;
                    one.type = gl.UNIFORM_BUFFER;
                    one.dataOffset = this._engine.propertyNameToID(uniformBlockName);
                    let location = one.location = gl2.getUniformBlockIndex(prog, uniformBlockName);
                    let bindingPoint = i;
                    gl2.uniformBlockBinding(this._program, location, bindingPoint);
                    this._uniformObjectMap[one.name] = one;
                    this._uniformMap.push(one);
                    this._addShaderUnifiormFun(one);
                }
            }
            this._complete = true;
        }
        _createShader(gl, str, type) {
            let shader = gl.createShader(type);
            gl.shaderSource(shader, str);
            gl.compileShader(shader);
            return shader;
        }
        _addShaderUnifiormFun(one) {
            var gl = this._gl;
            one.caller = this;
            var isArray = one.isArray;
            switch (one.type) {
                case gl.BOOL:
                    one.fun = this._uniform1i;
                    one.uploadedValue = new Array(1);
                    break;
                case gl.INT:
                    one.fun = isArray ? this._uniform1iv : this._uniform1i;
                    one.uploadedValue = new Array(1);
                    break;
                case gl.FLOAT:
                    one.fun = isArray ? this._uniform1fv : this._uniform1f;
                    one.uploadedValue = new Array(1);
                    break;
                case gl.FLOAT_VEC2:
                    one.fun = isArray ? this._uniform_vec2v : this._uniform_vec2;
                    one.uploadedValue = new Array(2);
                    break;
                case gl.FLOAT_VEC3:
                    one.fun = isArray ? this._uniform_vec3v : this._uniform_vec3;
                    one.uploadedValue = new Array(3);
                    break;
                case gl.FLOAT_VEC4:
                    one.fun = isArray ? this._uniform_vec4v : this._uniform_vec4;
                    one.uploadedValue = new Array(4);
                    break;
                case gl.FLOAT_MAT2:
                    one.fun = this._uniformMatrix2fv;
                    break;
                case gl.FLOAT_MAT3:
                    one.fun = isArray ? this._uniformMatrix3fv : this._uniformMatrix3f;
                    break;
                case gl.FLOAT_MAT4:
                    one.fun = isArray ? this._uniformMatrix4fv : this._uniformMatrix4f;
                    break;
                case gl.SAMPLER_2D:
                case gl.SAMPLER_2D_SHADOW:
                    gl.uniform1i(one.location, this._curActTexIndex);
                    one.textureID = this._engine._glTextureIDParams[this._curActTexIndex++];
                    one.fun = this._uniform_sampler2D;
                    break;
                case gl.SAMPLER_2D_ARRAY:
                    gl.uniform1i(one.location, this._curActTexIndex);
                    one.textureID = this._engine._glTextureIDParams[this._curActTexIndex++];
                    one.fun = this._uniform_sampler2DArray;
                    break;
                case 0x8b5f:
                    gl.uniform1i(one.location, this._curActTexIndex);
                    one.textureID = this._engine._glTextureIDParams[this._curActTexIndex++];
                    one.fun = this._uniform_sampler3D;
                    break;
                case gl.SAMPLER_CUBE:
                    gl.uniform1i(one.location, this._curActTexIndex);
                    one.textureID = this._engine._glTextureIDParams[this._curActTexIndex++];
                    one.fun = this._uniform_samplerCube;
                    break;
                case gl.UNIFORM_BUFFER:
                    one.fun = this._uniform_UniformBuffer;
                    break;
                default:
                    WebGLEngine._lastShaderError = `unknown uniform type (${one.type})`;
            }
        }
        getUniformMap() {
            return this._uniformMap;
        }
        bind() {
            return this.useProgram();
        }
        useProgram() {
            if (this._engine._glUseProgram === this)
                return false;
            this._gl.useProgram(this._program);
            this._engine._glUseProgram = this;
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_ShaderChange, 1);
            return true;
        }
        _uniform1f(one, value) {
            var uploadedValue = one.uploadedValue;
            if (uploadedValue[0] !== value) {
                this._gl.uniform1f(one.location, uploadedValue[0] = value);
                return 1;
            }
            return 0;
        }
        _uniform1fv(one, value) {
            if (value.length < 4) {
                var uploadedValue = one.uploadedValue;
                if (uploadedValue[0] !== value[0] || uploadedValue[1] !== value[1] || uploadedValue[2] !== value[2] || uploadedValue[3] !== value[3]) {
                    this._gl.uniform1fv(one.location, value);
                    uploadedValue[0] = value[0];
                    uploadedValue[1] = value[1];
                    uploadedValue[2] = value[2];
                    uploadedValue[3] = value[3];
                    return 1;
                }
                return 0;
            }
            else {
                this._gl.uniform1fv(one.location, value);
                return 1;
            }
        }
        _uniform_vec2(one, v) {
            var uploadedValue = one.uploadedValue;
            if (uploadedValue[0] !== v.x || uploadedValue[1] !== v.y) {
                this._gl.uniform2f(one.location, uploadedValue[0] = v.x, uploadedValue[1] = v.y);
                return 1;
            }
            return 0;
        }
        _uniform_vec2v(one, value) {
            if (value.length < 2) {
                var uploadedValue = one.uploadedValue;
                if (uploadedValue[0] !== value[0] || uploadedValue[1] !== value[1] || uploadedValue[2] !== value[2] || uploadedValue[3] !== value[3]) {
                    this._gl.uniform2fv(one.location, value);
                    uploadedValue[0] = value[0];
                    uploadedValue[1] = value[1];
                    uploadedValue[2] = value[2];
                    uploadedValue[3] = value[3];
                    return 1;
                }
                return 0;
            }
            else {
                this._gl.uniform2fv(one.location, value);
                return 1;
            }
        }
        _uniform_vec3(one, v) {
            var uploadedValue = one.uploadedValue;
            if (uploadedValue[0] !== v.x || uploadedValue[1] !== v.y || uploadedValue[2] !== v.z) {
                this._gl.uniform3f(one.location, uploadedValue[0] = v.x, uploadedValue[1] = v.y, uploadedValue[2] = v.z);
                return 1;
            }
            return 0;
        }
        _uniform_vec3v(one, v) {
            this._gl.uniform3fv(one.location, v);
            return 1;
        }
        _uniform_vec4(one, v) {
            var uploadedValue = one.uploadedValue;
            if (uploadedValue[0] !== v.x || uploadedValue[1] !== v.y || uploadedValue[2] !== v.z || uploadedValue[3] !== v.w) {
                this._gl.uniform4f(one.location, uploadedValue[0] = v.x, uploadedValue[1] = v.y, uploadedValue[2] = v.z, uploadedValue[3] = v.w);
                return 1;
            }
            return 0;
        }
        _uniform_vec4v(one, v) {
            this._gl.uniform4fv(one.location, v);
            return 1;
        }
        _uniformMatrix2fv(one, value) {
            this._gl.uniformMatrix2fv(one.location, false, value);
            return 1;
        }
        _uniformMatrix3f(one, value) {
            this._gl.uniformMatrix3fv(one.location, false, value.elements);
            return 1;
        }
        _uniformMatrix3fv(one, value) {
            this._gl.uniformMatrix3fv(one.location, false, value);
            return 1;
        }
        _uniformMatrix4f(one, m) {
            var value = m.elements;
            this._gl.uniformMatrix4fv(one.location, false, value);
            return 1;
        }
        _uniformMatrix4fv(one, m) {
            this._gl.uniformMatrix4fv(one.location, false, m);
            return 1;
        }
        _uniform1i(one, value) {
            var uploadedValue = one.uploadedValue;
            if (uploadedValue[0] !== value) {
                this._gl.uniform1i(one.location, uploadedValue[0] = value);
                return 1;
            }
            return 0;
        }
        _uniform1iv(one, value) {
            this._gl.uniform1iv(one.location, value);
            return 1;
        }
        _uniform_ivec2(one, value) {
            var uploadedValue = one.uploadedValue;
            if (uploadedValue[0] !== value[0] || uploadedValue[1] !== value[1]) {
                this._gl.uniform2i(one.location, uploadedValue[0] = value[0], uploadedValue[1] = value[1]);
                return 1;
            }
            return 0;
        }
        _uniform_ivec2v(one, value) {
            this._gl.uniform2iv(one.location, value);
            return 1;
        }
        _uniform_vec3i(one, value) {
            var uploadedValue = one.uploadedValue;
            if (uploadedValue[0] !== value[0] || uploadedValue[1] !== value[1] || uploadedValue[2] !== value[2]) {
                this._gl.uniform3i(one.location, uploadedValue[0] = value[0], uploadedValue[1] = value[1], uploadedValue[2] = value[2]);
                return 1;
            }
            return 0;
        }
        _uniform_vec3vi(one, value) {
            this._gl.uniform3iv(one.location, value);
            return 1;
        }
        _uniform_vec4i(one, value) {
            var uploadedValue = one.uploadedValue;
            if (uploadedValue[0] !== value[0] || uploadedValue[1] !== value[1] || uploadedValue[2] !== value[2] || uploadedValue[3] !== value[3]) {
                this._gl.uniform4i(one.location, uploadedValue[0] = value[0], uploadedValue[1] = value[1], uploadedValue[2] = value[2], uploadedValue[3] = value[3]);
                return 1;
            }
            return 0;
        }
        _uniform_vec4vi(one, value) {
            this._gl.uniform4iv(one.location, value);
            return 1;
        }
        _uniform_sampler2D(one, texture) {
            var value = texture ? texture._getSource() : Laya.Texture2D.errorTexture._getSource();
            var gl = this._gl;
            this._bindTexture(one.textureID, gl.TEXTURE_2D, value);
            return 0;
        }
        _uniform_sampler2DArray(one, texture) {
            var value = texture ? texture._getSource() : Laya.Texture2D.errorTexture._getSource();
            var gl = this._gl;
            this._bindTexture(one.textureID, gl.TEXTURE_2D_ARRAY, value);
            return 0;
        }
        _uniform_sampler3D(one, texture) {
            var value = texture ? texture._getSource() : Laya.Texture2D.errorTexture._getSource();
            var gl = this._gl;
            this._bindTexture(one.textureID, gl.TEXTURE_3D, value);
            return 0;
        }
        _uniform_samplerCube(one, texture) {
            var value = texture ? texture._getSource() : Laya.TextureCube.errorTexture._getSource();
            var gl = this._gl;
            this._bindTexture(one.textureID, gl.TEXTURE_CUBE_MAP, value);
            return 0;
        }
        _uniform_UniformBuffer(one, value) {
            value.bind(one.location);
            return 1;
        }
        _bindTexture(textureID, target, texture) {
            const gl = this._gl;
            if (this._engine._activedTextureID !== textureID) {
                gl.activeTexture(textureID);
                this._engine._activedTextureID = textureID;
            }
            const texID = this._engine._activedTextureID - this._gl.TEXTURE0;
            if (this._engine._activeTextures[texID] !== texture) {
                gl.bindTexture(target, texture);
                this._engine._activeTextures[texID] = texture;
            }
        }
        destroy() {
            super.destroy();
            const gl = this._gl;
            gl.deleteShader(this._vshader);
            gl.deleteShader(this._pshader);
            gl.deleteProgram(this._program);
            this._vshader = null;
            this._pshader = null;
            this._program = null;
            this._attributeMap = null;
            this._uniformMap = null;
            this._uniformObjectMap = null;
            this._gl = null;
            this._engine = null;
        }
    }

    class GLVertexState extends GLObject {
        constructor(engine) {
            super(engine);
            this._vertexDeclaration = [];
            if (!engine.isWebGL2)
                this._vaoExt = engine._supportCapatable.getExtension(exports.WebGLExtension.OES_vertex_array_object);
            this._vao = this.createVertexArray();
            this._angleInstancedArrays = this._engine._supportCapatable.getExtension(exports.WebGLExtension.ANGLE_instanced_arrays);
        }
        createVertexArray() {
            if (this._engine.isWebGL2)
                return this._gl.createVertexArray();
            else
                return this._vaoExt.createVertexArrayOES();
        }
        deleteVertexArray() {
            if (this._engine.isWebGL2)
                this._gl.deleteVertexArray(this._vao);
            else
                this._vaoExt.deleteVertexArrayOES(this._vao);
        }
        bindVertexArray() {
            if (this._engine._GLBindVertexArray == this)
                return;
            if (this._engine.isWebGL2)
                this._gl.bindVertexArray(this._vao);
            else
                this._vaoExt.bindVertexArrayOES(this._vao);
            this._engine._GLBindVertexArray = this;
        }
        unbindVertexArray() {
            if (this._engine.isWebGL2)
                this._gl.bindVertexArray(null);
            else
                this._vaoExt.bindVertexArrayOES(null);
            this._engine._GLBindVertexArray = null;
        }
        isVertexArray() {
            if (this._engine.isWebGL2)
                this._gl.isVertexArray(this._vao);
            else
                this._vaoExt.isVertexArrayOES(this._vao);
        }
        applyVertexBuffer(vertexBuffer) {
            this.clearVAO();
            this._vertexBuffers = vertexBuffer;
            if (this._engine._GLBindVertexArray == this) {
                this._vertexDeclaration.length = vertexBuffer.length;
                var i = 0;
                vertexBuffer.forEach(element => {
                    var verDec = element._shaderValues;
                    this._vertexDeclaration[i++] = element._shaderValues;
                    element.bind();
                    for (var k in verDec) {
                        var loc = parseInt(k);
                        var attribute = verDec[k];
                        this._gl.enableVertexAttribArray(loc);
                        this._gl.vertexAttribPointer(loc, attribute.elementCount, attribute.elementType, !!attribute.normalized, attribute.vertexStride, attribute.elementOffset);
                        if (element.instanceBuffer)
                            this.vertexAttribDivisor(loc, 1);
                    }
                });
            }
            else {
                throw "BufferState: must call bind() function first.";
            }
        }
        clearVAO() {
            for (let i = 0, n = this._vertexDeclaration.length; i < n; i++) {
                var verDec = this._vertexDeclaration[i];
                for (var k in verDec) {
                    var loc = parseInt(k);
                    this._gl.disableVertexAttribArray(loc);
                }
            }
        }
        applyIndexBuffer(indexBuffer) {
            if (indexBuffer == null) {
                return;
            }
            if (this._engine._GLBindVertexArray == this) {
                if (this._bindedIndexBuffer !== indexBuffer) {
                    indexBuffer._glBuffer.bindBuffer();
                    this._bindedIndexBuffer = indexBuffer;
                }
            }
            else {
                throw "BufferState: must call bind() function first.";
            }
        }
        vertexAttribDivisor(index, divisor) {
            if (this._engine.isWebGL2)
                this._gl.vertexAttribDivisor(index, divisor);
            else
                this._angleInstancedArrays.vertexAttribDivisorANGLE(index, divisor);
        }
        destroy() {
            super.destroy();
            this._gl;
            this.deleteVertexArray();
            this._gl = null;
            this._engine = null;
        }
    }

    class VertexArrayObject {
        constructor() {
        }
    }
    (function () {
        var glErrorShadow = {};
        function error(msg) {
            if (window.console && window.console.error) {
                window.console.error(msg);
            }
        }
        function log(msg) {
            if (window.console && window.console.log) {
                window.console.log(msg);
            }
        }
        function synthesizeGLError(err, opt_msg) {
            glErrorShadow[err] = true;
            if (opt_msg !== undefined) {
                error(opt_msg);
            }
        }
        function wrapGLError(gl) {
            var f = gl.getError;
            gl.getError = function () {
                var err;
                do {
                    err = f.apply(gl);
                    if (err != gl.NO_ERROR) {
                        glErrorShadow[err] = true;
                    }
                } while (err != gl.NO_ERROR);
                for (var err1 in glErrorShadow) {
                    if (glErrorShadow[err1]) {
                        delete glErrorShadow[err1];
                        return parseInt(err1);
                    }
                }
                return gl.NO_ERROR;
            };
        }
        var WebGLVertexArrayObjectOES = function WebGLVertexArrayObjectOES(ext) {
            var gl = ext.gl;
            this.ext = ext;
            this.isAlive = true;
            this.hasBeenBound = false;
            this.elementArrayBuffer = null;
            this.attribs = new Array(ext.maxVertexAttribs);
            for (var n = 0; n < this.attribs.length; n++) {
                var attrib = new WebGLVertexArrayObjectOES.VertexAttrib(gl);
                this.attribs[n] = attrib;
            }
            this.maxAttrib = 0;
        };
        WebGLVertexArrayObjectOES.VertexAttrib = function VertexAttrib(gl) {
            this.enabled = false;
            this.buffer = null;
            this.size = 4;
            this.type = gl.FLOAT;
            this.normalized = false;
            this.stride = 16;
            this.offset = 0;
            this.cached = "";
            this.recache();
        };
        WebGLVertexArrayObjectOES.VertexAttrib.prototype.recache = function recache() {
            this.cached = [this.size, this.type, this.normalized, this.stride, this.offset].join(":");
        };
        var OESVertexArrayObject = function OESVertexArrayObject(gl) {
            var self = this;
            this.gl = gl;
            wrapGLError(gl);
            var original = this.original = {
                getParameter: gl.getParameter,
                enableVertexAttribArray: gl.enableVertexAttribArray,
                disableVertexAttribArray: gl.disableVertexAttribArray,
                bindBuffer: gl.bindBuffer,
                getVertexAttrib: gl.getVertexAttrib,
                vertexAttribPointer: gl.vertexAttribPointer
            };
            gl.getParameter = function getParameter(pname) {
                if (pname == self.VERTEX_ARRAY_BINDING_OES) {
                    if (self.currentVertexArrayObject == self.defaultVertexArrayObject) {
                        return null;
                    }
                    else {
                        return self.currentVertexArrayObject;
                    }
                }
                return original.getParameter.apply(this, arguments);
            };
            gl.enableVertexAttribArray = function enableVertexAttribArray(index) {
                var vao = self.currentVertexArrayObject;
                vao.maxAttrib = Math.max(vao.maxAttrib, index);
                var attrib = vao.attribs[index];
                attrib.enabled = true;
                return original.enableVertexAttribArray.apply(this, arguments);
            };
            gl.disableVertexAttribArray = function disableVertexAttribArray(index) {
                var vao = self.currentVertexArrayObject;
                vao.maxAttrib = Math.max(vao.maxAttrib, index);
                var attrib = vao.attribs[index];
                attrib.enabled = false;
                return original.disableVertexAttribArray.apply(this, arguments);
            };
            gl.bindBuffer = function bindBuffer(target, buffer) {
                switch (target) {
                    case gl.ARRAY_BUFFER:
                        self.currentArrayBuffer = buffer;
                        break;
                    case gl.ELEMENT_ARRAY_BUFFER:
                        self.currentVertexArrayObject.elementArrayBuffer = buffer;
                        break;
                }
                return original.bindBuffer.apply(this, arguments);
            };
            gl.getVertexAttrib = function getVertexAttrib(index, pname) {
                var vao = self.currentVertexArrayObject;
                var attrib = vao.attribs[index];
                switch (pname) {
                    case gl.VERTEX_ATTRIB_ARRAY_BUFFER_BINDING:
                        return attrib.buffer;
                    case gl.VERTEX_ATTRIB_ARRAY_ENABLED:
                        return attrib.enabled;
                    case gl.VERTEX_ATTRIB_ARRAY_SIZE:
                        return attrib.size;
                    case gl.VERTEX_ATTRIB_ARRAY_STRIDE:
                        return attrib.stride;
                    case gl.VERTEX_ATTRIB_ARRAY_TYPE:
                        return attrib.type;
                    case gl.VERTEX_ATTRIB_ARRAY_NORMALIZED:
                        return attrib.normalized;
                    default:
                        return original.getVertexAttrib.apply(this, arguments);
                }
            };
            gl.vertexAttribPointer = function vertexAttribPointer(indx, size, type, normalized, stride, offset) {
                var vao = self.currentVertexArrayObject;
                vao.maxAttrib = Math.max(vao.maxAttrib, indx);
                var attrib = vao.attribs[indx];
                attrib.buffer = self.currentArrayBuffer;
                attrib.size = size;
                attrib.type = type;
                attrib.normalized = normalized;
                attrib.stride = stride;
                attrib.offset = offset;
                attrib.recache();
                return original.vertexAttribPointer.apply(this, arguments);
            };
            if (gl.instrumentExtension) {
                gl.instrumentExtension(this, "OES_vertex_array_object");
            }
            gl.canvas.addEventListener('webglcontextrestored', function () {
                log("OESVertexArrayObject emulation library context restored");
                self.reset_();
            }, true);
            this.reset_();
        };
        OESVertexArrayObject.prototype.VERTEX_ARRAY_BINDING_OES = 0x85B5;
        OESVertexArrayObject.prototype.reset_ = function reset_() {
            var contextWasLost = this.vertexArrayObjects !== undefined;
            if (contextWasLost) {
                for (var ii = 0; ii < this.vertexArrayObjects.length; ++ii) {
                    this.vertexArrayObjects.isAlive = false;
                }
            }
            var gl = this.gl;
            this.maxVertexAttribs = gl.getParameter(gl.MAX_VERTEX_ATTRIBS);
            this.defaultVertexArrayObject = new WebGLVertexArrayObjectOES(this);
            this.currentVertexArrayObject = null;
            this.currentArrayBuffer = null;
            this.vertexArrayObjects = [this.defaultVertexArrayObject];
            this.bindVertexArrayOES(null);
        };
        OESVertexArrayObject.prototype.createVertexArrayOES = function createVertexArrayOES() {
            var arrayObject = new WebGLVertexArrayObjectOES(this);
            this.vertexArrayObjects.push(arrayObject);
            return arrayObject;
        };
        OESVertexArrayObject.prototype.deleteVertexArrayOES = function deleteVertexArrayOES(arrayObject) {
            arrayObject.isAlive = false;
            this.vertexArrayObjects.splice(this.vertexArrayObjects.indexOf(arrayObject), 1);
            if (this.currentVertexArrayObject == arrayObject) {
                this.bindVertexArrayOES(null);
            }
        };
        OESVertexArrayObject.prototype.isVertexArrayOES = function isVertexArrayOES(arrayObject) {
            if (arrayObject && arrayObject instanceof WebGLVertexArrayObjectOES) {
                if (arrayObject.hasBeenBound && arrayObject.ext == this) {
                    return true;
                }
            }
            return false;
        };
        OESVertexArrayObject.prototype.bindVertexArrayOES = function bindVertexArrayOES(arrayObject) {
            var gl = this.gl;
            if (arrayObject && !arrayObject.isAlive) {
                synthesizeGLError(gl.INVALID_OPERATION, "bindVertexArrayOES: attempt to bind deleted arrayObject");
                return;
            }
            var original = this.original;
            var oldVAO = this.currentVertexArrayObject;
            this.currentVertexArrayObject = arrayObject || this.defaultVertexArrayObject;
            this.currentVertexArrayObject.hasBeenBound = true;
            var newVAO = this.currentVertexArrayObject;
            if (oldVAO == newVAO) {
                return;
            }
            if (!oldVAO || newVAO.elementArrayBuffer != oldVAO.elementArrayBuffer) {
                original.bindBuffer.call(gl, gl.ELEMENT_ARRAY_BUFFER, newVAO.elementArrayBuffer);
            }
            var currentBinding = this.currentArrayBuffer;
            var maxAttrib = Math.max(oldVAO ? oldVAO.maxAttrib : 0, newVAO.maxAttrib);
            for (var n = 0; n <= maxAttrib; n++) {
                var attrib = newVAO.attribs[n];
                var oldAttrib = oldVAO ? oldVAO.attribs[n] : null;
                if (!oldVAO || attrib.enabled != oldAttrib.enabled) {
                    if (attrib.enabled) {
                        original.enableVertexAttribArray.call(gl, n);
                    }
                    else {
                        original.disableVertexAttribArray.call(gl, n);
                    }
                }
                if (attrib.enabled) {
                    var bufferChanged = false;
                    if (!oldVAO || attrib.buffer != oldAttrib.buffer) {
                        if (currentBinding != attrib.buffer) {
                            original.bindBuffer.call(gl, gl.ARRAY_BUFFER, attrib.buffer);
                            currentBinding = attrib.buffer;
                        }
                        bufferChanged = true;
                    }
                    if (bufferChanged || attrib.cached != oldAttrib.cached) {
                        original.vertexAttribPointer.call(gl, n, attrib.size, attrib.type, attrib.normalized, attrib.stride, attrib.offset);
                    }
                }
            }
            if (this.currentArrayBuffer != currentBinding) {
                original.bindBuffer.call(gl, gl.ARRAY_BUFFER, this.currentArrayBuffer);
            }
        };
        window._setupVertexArrayObject = function (gl) {
            var original_getSupportedExtensions = gl.getSupportedExtensions;
            gl.getSupportedExtensions = function getSupportedExtensions() {
                var list = original_getSupportedExtensions.call(this) || [];
                if (list.indexOf("OES_vertex_array_object") < 0) {
                    list.push("OES_vertex_array_object");
                }
                return list;
            };
            var original_getExtension = gl.getExtension;
            gl.getExtension = function getExtension(name) {
                var ext = original_getExtension.call(this, name);
                if (ext) {
                    return ext;
                }
                if (name !== "OES_vertex_array_object") {
                    return null;
                }
                if (!this.__OESVertexArrayObject) {
                    console.log("Setup OES_vertex_array_object polyfill");
                    this.__OESVertexArrayObject = new OESVertexArrayObject(this);
                }
                return this.__OESVertexArrayObject;
            };
        };
    }());

    const extentionVendorPrefixes = ["", "WEBKIT_", "MOZ_"];
    class GlCapable {
        constructor(glEngine) {
            this._gl = glEngine.gl;
            this.initExtension(glEngine.isWebGL2);
            this.initCapable(glEngine.isWebGL2);
        }
        initCapable(isWebgl2) {
            this._capabilityMap = new Map();
            let value = isWebgl2 || !!(this.getExtension(exports.WebGLExtension.OES_element_index_uint));
            this._capabilityMap.set(Laya.RenderCapable.Element_Index_Uint32, value);
            this._capabilityMap.set(Laya.RenderCapable.Element_Index_Uint8, true);
            value = isWebgl2 || !!(this.getExtension(exports.WebGLExtension.OES_texture_float));
            this._capabilityMap.set(Laya.RenderCapable.TextureFormat_R32G32B32A32, value);
            value = isWebgl2 || !!(this.getExtension(exports.WebGLExtension.OES_texture_half_float));
            this._capabilityMap.set(Laya.RenderCapable.TextureFormat_R16G16B16A16, value);
            value = !!(this.getExtension(exports.WebGLExtension.EXT_texture_filter_anisotropic));
            this._capabilityMap.set(Laya.RenderCapable.Texture_anisotropic, value);
            if (isWebgl2) {
                value = !!this.getExtension(exports.WebGLExtension.EXT_color_buffer_float) || !!this.getExtension(exports.WebGLExtension.EXT_color_buffer_half_float);
            }
            else {
                value = ((!!this.getExtension(exports.WebGLExtension.OES_texture_half_float)) || (!!this.getExtension(exports.WebGLExtension.EXT_color_buffer_half_float))) && (!!this.getExtension(exports.WebGLExtension.OES_texture_half_float_linear));
            }
            this._capabilityMap.set(Laya.RenderCapable.RenderTextureFormat_R16G16B16A16, value);
            if (isWebgl2) {
                value = !!this.getExtension(exports.WebGLExtension.EXT_color_buffer_float) && !!this.getExtension(exports.WebGLExtension.OES_texture_float_linear);
            }
            else {
                value = (!!this.getExtension(exports.WebGLExtension.OES_texture_float)) && (!!this.getExtension(exports.WebGLExtension.OES_texture_float_linear));
            }
            this._capabilityMap.set(Laya.RenderCapable.RenderTextureFormat_R32G32B32A32, value);
            value = isWebgl2 || (!!this.getExtension(exports.WebGLExtension.WEBGL_depth_texture));
            this._capabilityMap.set(Laya.RenderCapable.RenderTextureFormat_Depth, value);
            value = isWebgl2;
            this._capabilityMap.set(Laya.RenderCapable.RenderTextureFormat_ShadowMap, value);
            value = isWebgl2 || (!!this.getExtension(exports.WebGLExtension.OES_vertex_array_object));
            this._capabilityMap.set(Laya.RenderCapable.Vertex_VAO, value);
            value = (isWebgl2 || (!!this.getExtension(exports.WebGLExtension.ANGLE_instanced_arrays)));
            this._capabilityMap.set(Laya.RenderCapable.DrawElement_Instance, value);
            value = (isWebgl2) || (!!this.getExtension(exports.WebGLExtension.EXT_shader_texture_lod));
            this._capabilityMap.set(Laya.RenderCapable.Shader_TextureLod, value);
            value = (!!this.getExtension(exports.WebGLExtension.WEBGL_compressed_texture_s3tc));
            this._capabilityMap.set(Laya.RenderCapable.COMPRESS_TEXTURE_S3TC, value);
            value = (!!this.getExtension(exports.WebGLExtension.WEBGL_compressed_texture_s3tc_srgb));
            this._capabilityMap.set(Laya.RenderCapable.COMPRESS_TEXTURE_S3TC_SRGB, value);
            value = (!!this.getExtension(exports.WebGLExtension.WEBGL_compressed_texture_pvrtc));
            this._capabilityMap.set(Laya.RenderCapable.COMPRESS_TEXTURE_PVRTC, value);
            value = (!!this.getExtension(exports.WebGLExtension.WEBGL_compressed_texture_etc1));
            this._capabilityMap.set(Laya.RenderCapable.COMPRESS_TEXTURE_ETC1, value);
            value = (!!this.getExtension(exports.WebGLExtension.WEBGL_compressed_texture_etc));
            this._capabilityMap.set(Laya.RenderCapable.COMPRESS_TEXTURE_ETC, value);
            value = (!!this.getExtension(exports.WebGLExtension.WEBGL_compressed_texture_astc));
            this._capabilityMap.set(Laya.RenderCapable.COMPRESS_TEXTURE_ASTC, value);
            value = (isWebgl2) || (!!this.getExtension(exports.WebGLExtension.EXT_sRGB));
            this._capabilityMap.set(Laya.RenderCapable.Texture_SRGB, value);
            value = (!!this.getExtension(exports.WebGLExtension.OES_texture_float_linear));
            this._capabilityMap.set(Laya.RenderCapable.Texture_FloatLinearFiltering, value);
            value = isWebgl2 || (!!this.getExtension(exports.WebGLExtension.OES_texture_half_float_linear));
            this._capabilityMap.set(Laya.RenderCapable.Texture_HalfFloatLinearFiltering, value);
            value = isWebgl2;
            this._capabilityMap.set(Laya.RenderCapable.MSAA, value);
            this._capabilityMap.set(Laya.RenderCapable.UnifromBufferObject, value);
            this._capabilityMap.set(Laya.RenderCapable.Texture3D, value);
            this._capabilityMap.set(Laya.RenderCapable.ComputeShader, false);
            this._capabilityMap.set(Laya.RenderCapable.StorageBuffer, false);
        }
        initExtension(isWebgl2) {
            this._extensionMap = new Map();
            const getGlExtension = (name) => {
                for (const k in extentionVendorPrefixes) {
                    let ext = this._gl.getExtension(extentionVendorPrefixes[k] + name);
                    if (ext)
                        return ext;
                }
                return null;
            };
            const setExtensionMap = (extension, value, map) => {
                value && map.set(extension, value);
            };
            const _extTextureFilterAnisotropic = getGlExtension("EXT_texture_filter_anisotropic");
            setExtensionMap(exports.WebGLExtension.EXT_texture_filter_anisotropic, _extTextureFilterAnisotropic, this._extensionMap);
            const _compressedTextureS3tc = getGlExtension("WEBGL_compressed_texture_s3tc");
            setExtensionMap(exports.WebGLExtension.WEBGL_compressed_texture_s3tc, _compressedTextureS3tc, this._extensionMap);
            const _compressdTextureS3tc_srgb = getGlExtension("WEBGL_compressed_texture_s3tc_srgb");
            setExtensionMap(exports.WebGLExtension.WEBGL_compressed_texture_s3tc_srgb, _compressdTextureS3tc_srgb, this._extensionMap);
            const _compressedTexturePvrtc = getGlExtension("WEBGL_compressed_texture_pvrtc");
            setExtensionMap(exports.WebGLExtension.WEBGL_compressed_texture_pvrtc, _compressedTexturePvrtc, this._extensionMap);
            const _compressedTextureEtc1 = getGlExtension("WEBGL_compressed_texture_etc1");
            setExtensionMap(exports.WebGLExtension.WEBGL_compressed_texture_etc1, _compressedTextureEtc1, this._extensionMap);
            const _compressedTextureETC = getGlExtension("WEBGL_compressed_texture_etc");
            setExtensionMap(exports.WebGLExtension.WEBGL_compressed_texture_etc, _compressedTextureETC, this._extensionMap);
            const _compressedTextureASTC = getGlExtension("WEBGL_compressed_texture_astc");
            setExtensionMap(exports.WebGLExtension.WEBGL_compressed_texture_astc, _compressedTextureASTC, this._extensionMap);
            const _oesTextureFloatLinear = getGlExtension("OES_texture_float_linear");
            setExtensionMap(exports.WebGLExtension.OES_texture_float_linear, _oesTextureFloatLinear, this._extensionMap);
            const _extColorBufferHalfFloat = getGlExtension("EXT_color_buffer_half_float");
            setExtensionMap(exports.WebGLExtension.EXT_color_buffer_half_float, _extColorBufferHalfFloat, this._extensionMap);
            if (isWebgl2) {
                const _extColorBufferFloat = getGlExtension("EXT_color_buffer_float");
                setExtensionMap(exports.WebGLExtension.EXT_color_buffer_float, _extColorBufferFloat, this._extensionMap);
            }
            else {
                if (window._setupVertexArrayObject)
                    window._setupVertexArrayObject(this._gl);
                const _vaoExt = getGlExtension("OES_vertex_array_object");
                setExtensionMap(exports.WebGLExtension.OES_vertex_array_object, _vaoExt, this._extensionMap);
                const _angleInstancedArrays = getGlExtension("ANGLE_instanced_arrays");
                setExtensionMap(exports.WebGLExtension.ANGLE_instanced_arrays, _angleInstancedArrays, this._extensionMap);
                const _oesTextureHalfFloat = getGlExtension("OES_texture_half_float");
                setExtensionMap(exports.WebGLExtension.OES_texture_half_float, _oesTextureHalfFloat, this._extensionMap);
                const _oesTextureHalfFloatLinear = getGlExtension("OES_texture_half_float_linear");
                setExtensionMap(exports.WebGLExtension.OES_texture_half_float_linear, _oesTextureHalfFloatLinear, this._extensionMap);
                const _oesTextureFloat = getGlExtension("OES_texture_float");
                setExtensionMap(exports.WebGLExtension.OES_texture_float, _oesTextureFloat, this._extensionMap);
                const _oes_element_index_uint = getGlExtension("OES_element_index_uint");
                setExtensionMap(exports.WebGLExtension.OES_element_index_uint, _oes_element_index_uint, this._extensionMap);
                const _extShaderTextureLod = getGlExtension("EXT_shader_texture_lod");
                setExtensionMap(exports.WebGLExtension.EXT_shader_texture_lod, _extShaderTextureLod, this._extensionMap);
                const _webgl_depth_texture = getGlExtension("WEBGL_depth_texture");
                setExtensionMap(exports.WebGLExtension.WEBGL_depth_texture, _webgl_depth_texture, this._extensionMap);
                const _sRGB = getGlExtension("EXT_sRGB");
                setExtensionMap(exports.WebGLExtension.EXT_sRGB, _sRGB, this._extensionMap);
                const OES_standard_derivatives = getGlExtension("OES_standard_derivatives");
                setExtensionMap(exports.WebGLExtension.OES_standard_derivatives, OES_standard_derivatives, this._extensionMap);
            }
        }
        getCapable(type) {
            return this._capabilityMap.get(type);
        }
        getExtension(type) {
            return this._extensionMap.get(type) || null;
        }
        turnOffSRGB() {
            this._extensionMap.set(exports.WebGLExtension.EXT_sRGB, null);
            this._capabilityMap.set(Laya.RenderCapable.Texture_SRGB, false);
        }
        turnOffCapableAndExtension(type, extension) {
            if (type) {
                this._capabilityMap.set(type, false);
            }
            if (extension) {
                this._extensionMap.set(extension, null);
            }
        }
    }

    class WebGLUniformBufferManager extends Laya.UniformBufferManager {
        constructor(engine, offsetAlignment) {
            super(true);
            this.engine = engine;
            this.byteAlign = offsetAlignment;
            engine.on("endFrame", this, this.endFrame);
            engine.on("startFrame", this, this.startFrame);
        }
        createGPUBuffer(size, name, data) {
            let buffer = this.engine.createBuffer(Laya.BufferTargetType.UNIFORM_BUFFER, Laya.BufferUsage.Dynamic);
            buffer.bindBuffer();
            buffer.setDataLength(size);
            if (data) {
                buffer.setData(data, 0);
            }
            return buffer;
        }
        writeBuffer(buffer, data, offset, size) {
            buffer.bindBuffer();
            let gl = this.engine.gl;
            gl.bufferSubData(buffer._glTarget, offset, new Float32Array(data, offset, size / 4));
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_UBOBufferUploadCount, 1);
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_UBOBufferUploadMemory, size / 1048576);
        }
    }

    class WebGLEngine extends Laya.EventDispatcher {
        get lost() {
            return this._lost;
        }
        constructor(config, webglMode = exports.WebGLMode.Auto) {
            super();
            this._framePassCount = 0;
            this._lost = false;
            this._propertyNameMap = {};
            this._propertyNameCounter = 0;
            this._IDCounter = 0;
            this._isShaderDebugMode = true;
            this._lastClearColor = new Laya.Color;
            this._lastClearDepth = -1;
            this._remapZ = true;
            this._screenInvertY = false;
            this._lodTextureSample = true;
            this._breakTextureSample = true;
            this._config = config;
            this._isWebGL2 = false;
            this._lastViewport = new Laya.Vector4(0, 0, 0, 0);
            this._lastClearColor = new Laya.Color(0, 0, 0, 0);
            this._lastScissor = new Laya.Vector4(0, 0, 0, 0);
            this._webglMode = webglMode;
            WebGLEngine.instance = this;
        }
        startFrame() {
            this._framePassCount = 0;
            this.event("startFrame", null);
        }
        endFrame() {
            this.event("endFrame", null);
        }
        getInnerWidth() {
            return this._globalWidth;
        }
        getInnerHeight() {
            return this._globalHeight;
        }
        resizeOffScreen(width, height) {
            this._globalWidth = width;
            this._globalHeight = height;
        }
        addTexGammaDefine(key, value) {
            WebGLEngine._texGammaDefine[key] = value;
        }
        get gl() {
            return this._context;
        }
        get isWebGL2() {
            return this._isWebGL2;
        }
        get webglConfig() {
            return this._config;
        }
        initRenderEngine(canvas) {
            let names;
            let gl;
            switch (this._webglMode) {
                case exports.WebGLMode.Auto:
                    names = ["webgl2", "experimental-webgl2", "webgl", "experimental-webgl"];
                    break;
                case exports.WebGLMode.WebGL1:
                    names = ["webgl", "experimental-webgl"];
                    break;
                case exports.WebGLMode.WebGL2:
                    names = ["webgl2", "experimental-webgl2"];
                    break;
            }
            for (let i = 0; i < names.length; i++) {
                try {
                    gl = canvas.getContext(names[i], this._config);
                }
                catch (e) {
                }
                if (gl) {
                    if (names[i] === 'webgl2' || names[i] === 'experimental-webgl2') {
                        this._isWebGL2 = true;
                    }
                    break;
                }
            }
            this._context = gl;
            this.scissorTest(true);
            this._initBindBufferMap();
            this._supportCapatable = new GlCapable(this);
            this._GLParams = new GLParams(this);
            this._GLRenderState = new GLRenderState(this);
            this._glTextureIDParams = [gl.TEXTURE0, gl.TEXTURE1, gl.TEXTURE2, gl.TEXTURE3, gl.TEXTURE4, gl.TEXTURE5, gl.TEXTURE6, gl.TEXTURE7, gl.TEXTURE8, gl.TEXTURE9, gl.TEXTURE10, gl.TEXTURE11, gl.TEXTURE12, gl.TEXTURE13, gl.TEXTURE14, gl.TEXTURE15, gl.TEXTURE16, gl.TEXTURE17, gl.TEXTURE18, gl.TEXTURE19, gl.TEXTURE20, gl.TEXTURE21, gl.TEXTURE22, gl.TEXTURE23, gl.TEXTURE24, gl.TEXTURE25, gl.TEXTURE26, gl.TEXTURE27, gl.TEXTURE28, gl.TEXTURE29, gl.TEXTURE30, gl.TEXTURE31];
            this._activedTextureID = gl.TEXTURE0;
            this._activeTextures = [];
            this._GLTextureContext = this.isWebGL2 ? new GL2TextureContext(this) : new GLTextureContext(this);
            this._GLRenderDrawContext = new GLRenderDrawContext(this);
            canvas.addEventListener("webglcontextlost", this.webglContextLost);
            Laya.Config._uniformBlock = Laya.Config.enableUniformBufferObject && this.getCapable(Laya.RenderCapable.UnifromBufferObject);
            Laya.Config.matUseUBO = Laya.Config.matUseUBO && this.getCapable(Laya.RenderCapable.UnifromBufferObject) && Laya.Config.enableUniformBufferObject;
            this._initBufferBlock();
        }
        _initBufferBlock() {
            const useUBO = (Laya.Config._uniformBlock || Laya.Config.matUseUBO);
            if (useUBO) {
                const gl = this._context;
                let offsetAlignment = gl.getParameter(gl.UNIFORM_BUFFER_OFFSET_ALIGNMENT);
                this.bufferMgr = new WebGLUniformBufferManager(this, offsetAlignment);
                let maxBlockCount = gl.getParameter(gl.MAX_UNIFORM_BUFFER_BINDINGS);
                this._uboBindingMap = new Array(maxBlockCount);
                for (let i = 0; i < maxBlockCount; i++) {
                    this._uboBindingMap[i] = { buffer: null, offset: 0, size: 0 };
                }
            }
        }
        webglContextLost(e) {
            console.log("lost webgl context");
            Laya.Laya.stage.event("GraphicContextLost", e);
            this._lost = true;
        }
        _initBindBufferMap() {
            this._GLBufferBindMap = {};
            this._GLBufferBindMap[Laya.BufferTargetType.ARRAY_BUFFER] = null;
            this._GLBufferBindMap[Laya.BufferTargetType.ELEMENT_ARRAY_BUFFER] = null;
            this._GLBufferBindMap[Laya.BufferTargetType.UNIFORM_BUFFER] = null;
        }
        _getbindBuffer(target) {
            return this._GLBufferBindMap[target];
        }
        _setbindBuffer(target, buffer) {
            this._GLBufferBindMap[target] = buffer;
        }
        _bindTexture(target, texture) {
            const texID = this._activedTextureID - this._context.TEXTURE0;
            if (this._activeTextures[texID] !== texture) {
                this._context.bindTexture(target, texture);
                this._activeTextures[texID] = texture;
            }
        }
        getCapable(capatableType) {
            return this._supportCapatable.getCapable(capatableType);
        }
        viewport(x, y, width, height) {
            const gl = this._context;
            const lv = this._lastViewport;
            if (Laya.LayaEnv.isConch) {
                gl.viewport(x, y, width, height);
            }
            else if (x !== lv.x || y !== lv.y || width !== lv.z || height !== lv.w) {
                gl.viewport(x, y, width, height);
                lv.setValue(x, y, width, height);
            }
        }
        scissor(x, y, width, height) {
            const gl = this._context;
            const lv = this._lastScissor;
            if (Laya.LayaEnv.isConch) {
                gl.scissor(x, y, width, height);
            }
            else if (x !== lv.x || y !== lv.y || width !== lv.z || height !== lv.w) {
                gl.scissor(x, y, width, height);
                lv.setValue(x, y, width, height);
            }
        }
        scissorTest(value) {
            if (this._scissorState == value)
                return;
            this._scissorState = value;
            if (value)
                this._context.enable(this._context.SCISSOR_TEST);
            else
                this._context.disable(this._context.SCISSOR_TEST);
        }
        clearRenderTexture(clearFlag, clearcolor = null, clearDepth = 1, clearStencilValue = 0) {
            var flag;
            if (clearFlag & Laya.RenderClearFlag.Color) {
                if (clearcolor && !this._lastClearColor.equal(clearcolor)) {
                    this._context.clearColor(clearcolor.r, clearcolor.g, clearcolor.b, clearcolor.a);
                    clearcolor.cloneTo(this._lastClearColor);
                }
                flag |= this.gl.COLOR_BUFFER_BIT;
            }
            if (clearFlag & Laya.RenderClearFlag.Depth) {
                if (this._lastClearDepth != clearDepth) {
                    this._context.clearDepth(clearDepth);
                    this._lastClearDepth = clearDepth;
                }
                this._GLRenderState.setDepthMask(true);
                flag |= this._context.DEPTH_BUFFER_BIT;
            }
            if (clearFlag & Laya.RenderClearFlag.Stencil) {
                this._context.clearStencil(clearStencilValue);
                this._GLRenderState.setStencilWrite(true);
                this._GLRenderState.setStencilWriteMask(0xFF);
                flag |= this._context.STENCIL_BUFFER_BIT;
            }
            if (flag)
                this._context.clear(flag);
        }
        copySubFrameBuffertoTex(texture, level, xoffset, yoffset, x, y, width, height) {
            this._bindTexture(texture.target, texture.resource);
            this._context.copyTexSubImage2D(texture.target, level, xoffset, yoffset, x, y, width, height);
        }
        colorMask(r, g, b, a) {
            this._context.colorMask(r, g, b, a);
        }
        getParams(params) {
            return this._GLParams.getParams(params);
        }
        createBuffer(targetType, bufferUsageType) {
            return new GLBuffer(this, targetType, bufferUsageType);
        }
        createShaderInstance(vs, ps, attributeMap) {
            return new GLShaderInstance(this, vs, ps, attributeMap);
        }
        createVertexState() {
            return new GLVertexState(this);
        }
        getTextureContext() {
            return this._GLTextureContext;
        }
        getDrawContext() {
            return this._GLRenderDrawContext;
        }
        propertyNameToID(name) {
            if (this._propertyNameMap[name] != null) {
                return this._propertyNameMap[name];
            }
            else {
                var id = this._propertyNameCounter++;
                this._propertyNameMap[name] = id;
                this._propertyNameMap[id] = name;
                return id;
            }
        }
        propertyIDToName(id) {
            return this._propertyNameMap[id];
        }
        getNamesByDefineData(defineData, out) {
            var maskMap = WebGLEngine._maskMap;
            var mask = defineData._mask;
            out.length = 0;
            for (var i = 0, n = defineData._length; i < n; i++) {
                var subMaskMap = maskMap[i];
                var subMask = mask[i];
                for (var j = 0; j < 32; j++) {
                    var d = 1 << j;
                    if (subMask > 0 && d > subMask)
                        break;
                    if (subMask & d)
                        out.push(subMaskMap[d]);
                }
            }
        }
        getDefineByName(name) {
            var define = WebGLEngine._defineMap[name];
            if (!define) {
                var maskMap = WebGLEngine._maskMap;
                var counter = WebGLEngine._defineCounter;
                var index = Math.floor(counter / 32);
                var value = 1 << counter % 32;
                define = new Laya.ShaderDefine(index, value);
                WebGLEngine._defineMap[name] = define;
                if (index == maskMap.length) {
                    maskMap.length++;
                    maskMap[index] = {};
                }
                maskMap[index][value] = name;
                WebGLEngine._defineCounter++;
            }
            return define;
        }
        uploadUniforms(shader, commandEncoder, shaderData, uploadUnTexture) {
            var data = shaderData._data;
            var shaderUniform = commandEncoder.getArrayData();
            var shaderCall = 0;
            for (var i = 0, n = shaderUniform.length; i < n; i++) {
                var one = shaderUniform[i];
                if (uploadUnTexture || one.textureID !== -1) {
                    var value = data[one.dataOffset];
                    if (value != null)
                        shaderCall += one.fun.call(one.caller, one, value);
                }
            }
            return shaderCall;
        }
        uploadOneUniforms(shader, shaderVariable, data) {
            shader.bind();
            if (shaderVariable && data != null)
                shaderVariable.fun.call(shaderVariable.caller, shaderVariable, data);
        }
        unbindVertexState() {
            if (this.isWebGL2)
                this._context.bindVertexArray(null);
            else
                this._supportCapatable.getExtension(exports.WebGLExtension.OES_vertex_array_object).bindVertexArrayOES(null);
            this._GLBindVertexArray = null;
        }
        hashRenderState(renderState) {
            let rasterMask = 0;
            {
                let bitOffset = 0;
                rasterMask |= (renderState.cull & 0x3) << bitOffset;
                bitOffset += 2;
                rasterMask |= (renderState.blend & 0x3) << bitOffset;
                bitOffset += 2;
                switch (renderState.blend) {
                    case Laya.BlendType.BLEND_DISABLE:
                        bitOffset += (4 + 4 + 3) * 2;
                        break;
                    case Laya.BlendType.BLEND_ENABLE_ALL:
                        rasterMask |= (renderState.srcBlend & 0xF) << bitOffset;
                        bitOffset += 4;
                        rasterMask |= (renderState.dstBlend & 0xF) << bitOffset;
                        bitOffset += 4;
                        rasterMask |= (renderState.blendEquation & 0x7) << bitOffset;
                        bitOffset += 3;
                        bitOffset += 4 + 4 + 3;
                        break;
                    case Laya.BlendType.BLEND_ENABLE_SEPERATE:
                        rasterMask |= (renderState.srcBlendRGB & 0xF) << bitOffset;
                        bitOffset += 4;
                        rasterMask |= (renderState.dstBlendRGB & 0xF) << bitOffset;
                        bitOffset += 4;
                        rasterMask |= (renderState.blendEquationRGB & 0x7) << bitOffset;
                        bitOffset += 3;
                        rasterMask |= (renderState.srcBlendAlpha & 0xF) << bitOffset;
                        bitOffset += 4;
                        rasterMask |= (renderState.dstBlendAlpha & 0xF) << bitOffset;
                        bitOffset += 4;
                        rasterMask |= (renderState.blendEquationAlpha & 0x7) << bitOffset;
                        bitOffset += 3;
                        break;
                }
            }
            let depthStencilMask = 0;
            {
                let bitOffset = 0;
                depthStencilMask |= (renderState.depthTest & 0xF) << bitOffset;
                bitOffset += 4;
                depthStencilMask |= (renderState.depthWrite ? 1 : 0) << bitOffset;
                bitOffset += 1;
                depthStencilMask |= (renderState.depthBias ? 1 : 0) << bitOffset;
                bitOffset += 1;
                depthStencilMask |= (renderState.stencilTest & 0xF) << bitOffset;
                bitOffset += 4;
                depthStencilMask |= (renderState.stencilOp.x & 0x7) << bitOffset;
                bitOffset += 3;
                depthStencilMask |= (renderState.stencilOp.y & 0x7) << bitOffset;
                bitOffset += 3;
                depthStencilMask |= (renderState.stencilOp.z & 0x7) << bitOffset;
                bitOffset += 3;
                depthStencilMask |= (renderState.stencilWrite ? 1 : 0) << bitOffset;
                bitOffset += 1;
            }
            let stencilMask = 0;
            {
                let bitOffset = 0;
                stencilMask |= (renderState.stencilReadMask & 0xFF) << bitOffset;
                bitOffset += 8;
                stencilMask |= (renderState.stencilWriteMask & 0xFF) << bitOffset;
                bitOffset += 8;
                stencilMask |= (renderState.stencilRef & 0xFF) << bitOffset;
                bitOffset += 8;
            }
            renderStateHashF32[0] = renderState.depthBiasConstant;
            renderStateHashF32[1] = renderState.depthBiasSlopeScale;
            renderStateHashF32[2] = renderState.depthBiasClamp;
            return `${rasterMask}_${depthStencilMask}_${stencilMask}_${renderStateHashU32.join()}`;
        }
    }
    WebGLEngine._texGammaDefine = {};
    WebGLEngine._lastFrameBuffer = null;
    WebGLEngine._lastFrameBuffer_WebGLOBJ = null;
    WebGLEngine._defineMap = {};
    WebGLEngine._defineCounter = 0;
    WebGLEngine._maskMap = [];
    const renderStateHashF32 = new Float32Array(3);
    const renderStateHashU32 = new Uint32Array(renderStateHashF32.buffer);

    class WebGLUniformBufferBase {
        constructor() {
            this.destroyed = false;
        }
        setInt(index, value) {
            let uniform = this.descriptor.uniforms.get(index);
            if (uniform) {
                uniform.view[0] = value;
                this.needUpload = true;
            }
        }
        setFloat(index, value) {
            let uniform = this.descriptor.uniforms.get(index);
            if (uniform) {
                uniform.view[0] = value;
                this.needUpload = true;
            }
        }
        setVector2(index, value) {
            let uniform = this.descriptor.uniforms.get(index);
            if (uniform) {
                uniform.view[0] = value.x;
                uniform.view[1] = value.y;
                this.needUpload = true;
            }
        }
        setVector3(index, value) {
            let uniform = this.descriptor.uniforms.get(index);
            if (uniform) {
                uniform.view[0] = value.x;
                uniform.view[1] = value.y;
                uniform.view[2] = value.z;
                this.needUpload = true;
            }
        }
        setVector4(index, value) {
            let uniform = this.descriptor.uniforms.get(index);
            if (uniform) {
                uniform.view[0] = value.x;
                uniform.view[1] = value.y;
                uniform.view[2] = value.z;
                uniform.view[3] = value.w;
                this.needUpload = true;
            }
        }
        setMatrix3x3(index, value) {
            let uniform = this.descriptor.uniforms.get(index);
            if (uniform) {
                let element = value.elements;
                for (let i = 0; i < 3; i++) {
                    for (let j = 0; j < 3; j++) {
                        uniform.view[i * 4 + j] = element[i * 3 + j];
                    }
                }
                this.needUpload = true;
            }
        }
        setMatrix4x4(index, value) {
            let uniform = this.descriptor.uniforms.get(index);
            if (uniform) {
                uniform.view.set(value.elements);
                this.needUpload = true;
            }
        }
        setBuffer(index, value) {
            let uniform = this.descriptor.uniforms.get(index);
            if (uniform) {
                uniform.view.set(value);
                this.needUpload = true;
            }
        }
        setArrayBuffer(index, value) {
            let uniform = this.descriptor.uniforms.get(index);
            if (uniform) {
                let arrayLength = uniform.arrayLength;
                let size = uniform.size;
                let alignStride = uniform.alignStride;
                for (let i = 0; i < arrayLength; i++) {
                    uniform.view.set(value.subarray(i * size, (i + 1) * size), i * alignStride);
                }
                this.needUpload = true;
            }
        }
        setMatrix3x3Array(index, value) {
            let uniform = this.descriptor.uniforms.get(index);
            if (uniform) {
                let arrayLength = uniform.arrayLength;
                uniform.size;
                let alignStride = uniform.alignStride;
                for (let i = 0; i < arrayLength; i++) {
                    for (let j = 0; j < 3; j++) {
                        for (let k = 0; k < 3; k++) {
                            uniform.view[i * alignStride + j * 4 + k] = value[i * 9 + j * 3 + k];
                        }
                    }
                }
                this.needUpload = true;
            }
        }
        setUniformData(index, type, data) {
            let uniform = this.descriptor.uniforms.get(index);
            if (uniform) {
                switch (type) {
                    case Laya.ShaderDataType.Bool:
                        if (uniform.arrayLength > 0) {
                            console.warn("ShaderDataType.Bool array not support");
                        }
                        else {
                            this.setInt(index, data ? 1 : 0);
                        }
                        break;
                    case Laya.ShaderDataType.Int:
                        if (uniform.arrayLength > 0) {
                            this.setArrayBuffer(index, data);
                        }
                        else {
                            this.setInt(index, data);
                        }
                        break;
                    case Laya.ShaderDataType.Float:
                        if (uniform.arrayLength > 0) {
                            this.setArrayBuffer(index, data);
                        }
                        else {
                            this.setFloat(index, data);
                        }
                        break;
                    case Laya.ShaderDataType.Vector2:
                        if (uniform.arrayLength > 0) {
                            this.setArrayBuffer(index, data);
                        }
                        else {
                            this.setVector2(index, data);
                        }
                        break;
                    case Laya.ShaderDataType.Vector3:
                        if (uniform.arrayLength > 0) {
                            this.setArrayBuffer(index, data);
                        }
                        else {
                            this.setVector3(index, data);
                        }
                        break;
                    case Laya.ShaderDataType.Vector4u:
                    case Laya.ShaderDataType.Vector4:
                    case Laya.ShaderDataType.Color:
                        if (uniform.arrayLength > 0) {
                            this.setArrayBuffer(index, data);
                        }
                        else {
                            this.setVector4(index, data);
                        }
                        break;
                    case Laya.ShaderDataType.Matrix3x3:
                        if (uniform.arrayLength > 0) {
                            this.setMatrix3x3Array(index, data);
                        }
                        else {
                            this.setMatrix3x3(index, data);
                        }
                        break;
                    case Laya.ShaderDataType.Matrix4x4:
                        if (uniform.arrayLength > 0) {
                            this.setArrayBuffer(index, data);
                        }
                        else {
                            this.setMatrix4x4(index, data);
                        }
                        break;
                    case Laya.ShaderDataType.Buffer:
                        break;
                    case Laya.ShaderDataType.None:
                    case Laya.ShaderDataType.Texture2D:
                    case Laya.ShaderDataType.Texture3D:
                    case Laya.ShaderDataType.TextureCube:
                    case Laya.ShaderDataType.Texture2DArray:
                }
            }
        }
    }

    class WebGLUniformBufferDescriptor {
        get byteLength() {
            return this._byteLength;
        }
        constructor(name) {
            this._currentLength = 0;
            this._byteLength = 0;
            this._maxAlignment = 4;
            this.name = name;
            this.uniforms = new Map();
        }
        alignmentPadding(alignment) {
            let pointer = this._currentLength;
            let endPadding = pointer % alignment;
            if (endPadding != 0) {
                endPadding = alignment - endPadding;
                this._currentLength += endPadding;
                this._byteLength += endPadding * 4;
            }
            this._maxAlignment = Math.max(this._maxAlignment, alignment);
        }
        addUniformItem(index, size, alignStride, arraySize, tsc) {
            if (arraySize > 0) {
                alignStride = alignStride > 4 ? alignStride : 4;
                this.alignmentPadding(4);
                let arrayStride = arraySize * alignStride;
                let view;
                let uniform = {
                    index: index,
                    view: view,
                    size: size,
                    alignStride: alignStride,
                    offset: this._currentLength * 4,
                    dataView: tsc,
                    viewByteLength: tsc.BYTES_PER_ELEMENT * arrayStride,
                    arrayLength: arraySize,
                };
                this.uniforms.set(index, uniform);
                this._currentLength += arrayStride;
                this._byteLength += uniform.viewByteLength;
            }
            else {
                this.alignmentPadding(size <= 2 ? size : 4);
                let view;
                let uniform = {
                    index: index,
                    view: view,
                    size: size,
                    alignStride: alignStride,
                    offset: this._currentLength * 4,
                    dataView: tsc,
                    viewByteLength: tsc.BYTES_PER_ELEMENT * alignStride,
                    arrayLength: 0,
                };
                this.uniforms.set(index, uniform);
                this._currentLength += size;
                this._byteLength += size * tsc.BYTES_PER_ELEMENT;
            }
        }
        addUniform(index, type, arraySize = 0) {
            let alignStride = 0;
            switch (type) {
                case Laya.ShaderDataType.Int:
                case Laya.ShaderDataType.Bool:
                    alignStride = 1;
                    this.addUniformItem(index, 1, alignStride, arraySize, Int32Array);
                    break;
                case Laya.ShaderDataType.Float:
                    alignStride = 1;
                    this.addUniformItem(index, 1, alignStride, arraySize, Float32Array);
                    break;
                case Laya.ShaderDataType.Vector2:
                    alignStride = 2;
                    this.addUniformItem(index, 2, alignStride, arraySize, Float32Array);
                    break;
                case Laya.ShaderDataType.Vector3:
                    alignStride = 3;
                    this.addUniformItem(index, 3, alignStride, arraySize, Float32Array);
                    break;
                case Laya.ShaderDataType.Vector4u:
                    alignStride = 4;
                    this.addUniformItem(index, 4, alignStride, arraySize, Uint32Array);
                    break;
                case Laya.ShaderDataType.Vector4:
                case Laya.ShaderDataType.Color:
                    alignStride = 4;
                    this.addUniformItem(index, 4, alignStride, arraySize, Float32Array);
                    break;
                case Laya.ShaderDataType.Matrix3x3:
                    alignStride = 12;
                    this.addUniformItem(index, 12, alignStride, arraySize, Float32Array);
                    break;
                case Laya.ShaderDataType.Matrix4x4:
                    alignStride = 16;
                    this.addUniformItem(index, 16, alignStride, arraySize, Float32Array);
                    break;
                case Laya.ShaderDataType.Buffer:
                    console.log("ShaderDataType.Buffer not support");
                    break;
                case Laya.ShaderDataType.Texture2D:
                case Laya.ShaderDataType.Texture3D:
                case Laya.ShaderDataType.TextureCube:
                case Laya.ShaderDataType.Texture2DArray:
                case Laya.ShaderDataType.None:
            }
        }
        finish(alignment = 0) {
            alignment = alignment > this._maxAlignment ? alignment : this._maxAlignment;
            this._maxAlignment = alignment;
            this.alignmentPadding(alignment);
        }
        clone() {
            let descriptor = new WebGLUniformBufferDescriptor(this.name);
            this.cloneTo(descriptor);
            return descriptor;
        }
        cloneTo(destObject) {
            this.uniforms.forEach(uniform => {
                destObject.addUniformItem(uniform.index, uniform.size, uniform.alignStride, uniform.arrayLength, uniform.dataView);
            });
            destObject.finish(this._maxAlignment);
        }
        destroy() {
            this.uniforms.clear();
        }
    }

    class WebGLUniformBuffer extends WebGLUniformBufferBase {
        constructor(name) {
            super();
            this.name = name;
            this.descriptor = new WebGLUniformBufferDescriptor(name);
        }
        create() {
            let descriptor = this.descriptor;
            descriptor.finish();
            const buffer = new Uint8Array(descriptor.byteLength).buffer;
            this._data = new Float32Array(buffer);
            for (const [key, uniform] of descriptor.uniforms) {
                uniform.view = new uniform.dataView(buffer, uniform.offset, uniform.viewByteLength / uniform.dataView.BYTES_PER_ELEMENT);
            }
            this._buffer = Laya.LayaGL.renderEngine.createBuffer(Laya.BufferTargetType.UNIFORM_BUFFER, Laya.BufferUsage.Dynamic);
            this._buffer.bindBuffer();
            this._buffer.setDataLength(descriptor.byteLength);
            this.needUpload = true;
        }
        addUniform(index, type, arraySize = 0) {
            this.descriptor.addUniform(index, type, arraySize);
        }
        upload() {
            if (this.needUpload) {
                this._buffer.setData(this._data, 0);
                this.needUpload = false;
            }
        }
        bind(location) {
            this._buffer.bindBufferBase(location);
        }
        clone() {
            let buffer = new WebGLUniformBuffer(this.name);
            this.cloneTo(buffer);
            return buffer;
        }
        cloneTo(dest) {
            this.descriptor.cloneTo(dest.descriptor);
            dest.create();
            dest._data.set(this._data);
        }
        destroy() {
            this._data = null;
            this._buffer.destroy();
            this.descriptor.destroy();
            this.descriptor = null;
            this.destroyed = true;
        }
    }

    class WebGLSubUniformBuffer extends WebGLUniformBufferBase {
        upload() {
            this.needUpload && this.bufferBlock.needUpload();
        }
        bind(location) {
            let buffer = this.bufferBlock.cluster.buffer;
            buffer.bindBufferRange(location, this.bufferBlock.offset, this.bufferBlock.size);
        }
        constructor(name, uniformMap, mgr, data) {
            super();
            this.name = name;
            this.manager = mgr;
            this.data = data;
            this.uniformMap = uniformMap;
            let descriptor = new WebGLUniformBufferDescriptor(name);
            uniformMap.forEach(uniform => {
                descriptor.addUniform(uniform.id, uniform.uniformtype, uniform.arrayLength);
            });
            descriptor.finish(this.manager.byteAlign / 4);
            let bufferSize = descriptor.byteLength;
            this.descriptor = descriptor;
            this.size = bufferSize;
            this.bufferBlock = mgr.getBlock(bufferSize, this);
            this.needUpload = true;
        }
        updateOver() {
            this.needUpload = false;
        }
        clearGPUBufferBind() {
        }
        notifyGPUBufferChange(info) {
            this.offset = this.bufferBlock.offset;
            this.needUpload = true;
            this.descriptor.uniforms.forEach(uniform => {
                let size = uniform.viewByteLength / uniform.dataView.BYTES_PER_ELEMENT;
                let offset = uniform.offset + this.bufferBlock.offset;
                uniform.view = new uniform.dataView(this.bufferBlock.cluster.data, offset, size);
            });
            this.needUpload = true;
        }
        destroy() {
            this.name = null;
            this.data = null;
            this.uniformMap = null;
            this.descriptor.destroy();
            this.descriptor = null;
            this.manager.freeBlock(this.bufferBlock);
            this.destroyed = true;
        }
    }

    class WebGLShaderData extends Laya.ShaderData {
        get renderStateChanged() {
            return this._renderStateChanged;
        }
        updateRenderState() {
            var _a, _b, _c;
            this._renderStateChanged = false;
            const datas = this.getData();
            const renderState = this.renderState;
            let depthWrite = datas[Laya.Shader3D.DEPTH_WRITE];
            depthWrite = depthWrite !== null && depthWrite !== void 0 ? depthWrite : Laya.RenderState.Default.depthWrite;
            renderState.depthWrite = depthWrite;
            let depthTest = datas[Laya.Shader3D.DEPTH_TEST];
            depthTest = depthTest !== null && depthTest !== void 0 ? depthTest : Laya.RenderState.Default.depthTest;
            renderState.depthTest = depthTest;
            let stencilWrite = datas[Laya.Shader3D.STENCIL_WRITE];
            stencilWrite = stencilWrite !== null && stencilWrite !== void 0 ? stencilWrite : Laya.RenderState.Default.stencilWrite;
            renderState.stencilWrite = stencilWrite;
            let stencilWriteMask = ((_a = datas[Laya.Shader3D.STENCIL_WRITE_MASK]) !== null && _a !== void 0 ? _a : Laya.RenderState.Default.stencilWriteMask);
            renderState.stencilWriteMask = stencilWriteMask;
            let stencilOp = datas[Laya.Shader3D.STENCIL_Op];
            stencilOp = stencilOp !== null && stencilOp !== void 0 ? stencilOp : Laya.RenderState.Default.stencilOp;
            renderState.stencilOp.set(stencilOp.x, stencilOp.y, stencilOp.z);
            let stencilTest = datas[Laya.Shader3D.STENCIL_TEST];
            stencilTest = stencilTest !== null && stencilTest !== void 0 ? stencilTest : Laya.RenderState.Default.stencilTest;
            renderState.stencilTest = stencilTest;
            let stencilReadMask = (_b = datas[Laya.Shader3D.STENCIL_READ_MASK]) !== null && _b !== void 0 ? _b : Laya.RenderState.Default.stencilReadMask;
            renderState.stencilReadMask = stencilReadMask;
            var stencilRef = datas[Laya.Shader3D.STENCIL_Ref];
            stencilRef = stencilRef !== null && stencilRef !== void 0 ? stencilRef : Laya.RenderState.Default.stencilRef;
            renderState.stencilRef = stencilRef;
            let depthBias = (_c = datas[Laya.Shader3D.DEPTH_BIAS]) !== null && _c !== void 0 ? _c : Laya.RenderState.Default.depthBias;
            renderState.depthBias = depthBias;
            let depthBiasConstant = datas[Laya.Shader3D.DEPTH_BIAS_CONSTANT];
            depthBiasConstant = depthBiasConstant !== null && depthBiasConstant !== void 0 ? depthBiasConstant : Laya.RenderState.Default.depthBiasConstant;
            renderState.depthBiasConstant = depthBiasConstant;
            let depthBiasSlopeScale = datas[Laya.Shader3D.DEPTH_BIAS_SLOPESCALE];
            depthBiasSlopeScale = depthBiasSlopeScale !== null && depthBiasSlopeScale !== void 0 ? depthBiasSlopeScale : Laya.RenderState.Default.depthBiasSlopeScale;
            renderState.depthBiasSlopeScale = depthBiasSlopeScale;
            let depthBiasClamp = datas[Laya.Shader3D.DEPTH_BIAS_CLAMP];
            depthBiasClamp = depthBiasClamp !== null && depthBiasClamp !== void 0 ? depthBiasClamp : Laya.RenderState.Default.depthBiasClamp;
            renderState.depthBiasClamp = depthBiasClamp;
            let blend = datas[Laya.Shader3D.BLEND];
            blend = blend !== null && blend !== void 0 ? blend : Laya.RenderState.Default.blend;
            renderState.blend = blend;
            let blendEquation = datas[Laya.Shader3D.BLEND_EQUATION];
            blendEquation = blendEquation !== null && blendEquation !== void 0 ? blendEquation : Laya.RenderState.Default.blendEquation;
            renderState.blendEquation = blendEquation;
            let srcBlend = datas[Laya.Shader3D.BLEND_SRC];
            srcBlend = srcBlend !== null && srcBlend !== void 0 ? srcBlend : Laya.RenderState.Default.srcBlend;
            renderState.srcBlend = srcBlend;
            let dstBlend = datas[Laya.Shader3D.BLEND_DST];
            dstBlend = dstBlend !== null && dstBlend !== void 0 ? dstBlend : Laya.RenderState.Default.dstBlend;
            renderState.dstBlend = dstBlend;
            let blendEquationRGB = datas[Laya.Shader3D.BLEND_EQUATION_RGB];
            blendEquationRGB = blendEquationRGB !== null && blendEquationRGB !== void 0 ? blendEquationRGB : Laya.RenderState.Default.blendEquationRGB;
            renderState.blendEquationRGB = blendEquationRGB;
            let blendEquationAlpha = datas[Laya.Shader3D.BLEND_EQUATION_ALPHA];
            blendEquationAlpha = blendEquationAlpha !== null && blendEquationAlpha !== void 0 ? blendEquationAlpha : Laya.RenderState.Default.blendEquationAlpha;
            renderState.blendEquationAlpha = blendEquationAlpha;
            let srcRGB = datas[Laya.Shader3D.BLEND_SRC_RGB];
            srcRGB = srcRGB !== null && srcRGB !== void 0 ? srcRGB : Laya.RenderState.Default.srcBlendRGB;
            renderState.srcBlendRGB = srcRGB;
            let dstRGB = datas[Laya.Shader3D.BLEND_DST_RGB];
            dstRGB = dstRGB !== null && dstRGB !== void 0 ? dstRGB : Laya.RenderState.Default.dstBlendRGB;
            renderState.dstBlendRGB = dstRGB;
            let srcAlpha = datas[Laya.Shader3D.BLEND_SRC_ALPHA];
            srcAlpha = srcAlpha !== null && srcAlpha !== void 0 ? srcAlpha : Laya.RenderState.Default.srcBlendAlpha;
            renderState.srcBlendAlpha = srcAlpha;
            let dstAlpha = datas[Laya.Shader3D.BLEND_DST_ALPHA];
            dstAlpha = dstAlpha !== null && dstAlpha !== void 0 ? dstAlpha : Laya.RenderState.Default.dstBlendAlpha;
            renderState.dstBlendAlpha = dstAlpha;
            let cull = datas[Laya.Shader3D.CULL];
            cull = cull !== null && cull !== void 0 ? cull : Laya.RenderState.Default.cull;
            renderState.cull = cull;
            const engine = WebGLEngine.instance;
            const hash = engine.hashRenderState(renderState);
            renderState.hash = hash;
            this._renderStateChanged = false;
        }
        _checkRenderState(index) {
            if (Laya.isRenderStateProperty(index)) {
                this._renderStateChanged = true;
            }
        }
        constructor(ownerResource = null) {
            super(ownerResource);
            this._data = null;
            this._defineDatas = new WebDefineDatas();
            this._id = WebGLShaderData.pointerCount++;
            this._needCacheData = false;
            this._updateCacheArray = null;
            this._subUboBufferNumber = 0;
            this._renderStateChanged = true;
            this.renderState = new Laya.RenderState();
            this._initData();
        }
        _initData() {
            this._data = {};
            this._updateCacheArray = {};
            this._gammaColorMap = new Map();
            this._uniformBuffers = new Map();
            this._subUniformBuffers = new Map();
            this._uniformBuffersPropertyMap = new Map();
        }
        createUniformBuffer(name, uniformMap, needUpdata = false) {
            if (this._uniformBuffers.has(name)) {
                if (needUpdata) {
                    this._updateUBOBuffer(name);
                }
                return this._uniformBuffers.get(name);
            }
            this._needCacheData = true;
            let uboBuffer = new WebGLUniformBuffer(name);
            uniformMap.forEach(uniform => {
                uboBuffer.addUniform(uniform.id, uniform.uniformtype, uniform.arrayLength);
            });
            uboBuffer.create();
            this._uniformBuffers.set(name, uboBuffer);
            let id = Laya.Shader3D.propertyNameToID(name);
            this._data[id] = uboBuffer;
            uniformMap.forEach(uniform => {
                let uniformId = uniform.id;
                let data = this._data[uniformId];
                if (data != null) {
                    uboBuffer.setUniformData(uniformId, uniform.uniformtype, data);
                }
                this._uniformBuffersPropertyMap.set(uniformId, uboBuffer);
            });
            uboBuffer.needUpload && uboBuffer.upload();
            return uboBuffer;
        }
        _updateUBOBuffer(name) {
            if (!Laya.Config._uniformBlock) {
                return;
            }
            let buffer = this._uniformBuffers.get(name) || this._subUniformBuffers.get(name);
            if (!buffer) {
                return;
            }
            for (var i in this._updateCacheArray) {
                let index = parseInt(i);
                let ubo = this._uniformBuffersPropertyMap.get(index);
                if (ubo) {
                    this._updateCacheArray[i].call(ubo, index, this._data[index]);
                }
            }
            this._updateCacheArray = {};
            buffer.needUpload && buffer.upload();
        }
        createSubUniformBuffer(name, cacheName, uniformMap) {
            let subBuffer = this._subUniformBuffers.get(cacheName);
            if (subBuffer) {
                if (this._subUboBufferNumber < 2) {
                    for (var i in this._updateCacheArray) {
                        let index = parseInt(i);
                        let ubo = this._uniformBuffersPropertyMap.get(index);
                        if (ubo) {
                            this._updateCacheArray[i].call(ubo, index, this._data[index]);
                        }
                    }
                    this._updateCacheArray = {};
                }
                else {
                    uniformMap.forEach((uniform, index) => {
                        if (this._data[index] && this._updateCacheArray[index]) {
                            this._updateCacheArray[index].call(subBuffer, index, this._data[index]);
                        }
                    });
                }
                return subBuffer;
            }
            let engine = WebGLEngine.instance;
            let mgr = engine.bufferMgr;
            let uniformBuffer = new WebGLSubUniformBuffer(name, uniformMap, mgr, this);
            this._subUboBufferNumber++;
            this._needCacheData = true;
            uniformBuffer.notifyGPUBufferChange();
            this._subUniformBuffers.set(cacheName, uniformBuffer);
            let id = Laya.Shader3D.propertyNameToID(name);
            this._data[id] = uniformBuffer;
            uniformMap.forEach(uniform => {
                let uniformId = uniform.id;
                let data = this._data[uniformId];
                if (data != null) {
                    uniformBuffer.setUniformData(uniformId, uniform.uniformtype, data);
                }
                this._uniformBuffersPropertyMap.set(uniformId, uniformBuffer);
            });
            return uniformBuffer;
        }
        getData() {
            return this._data;
        }
        addDefine(define) {
            this._defineDatas.add(define);
        }
        addDefines(define) {
            this._defineDatas.addDefineDatas(define);
        }
        removeDefine(define) {
            this._defineDatas.remove(define);
        }
        removeDefines(defines) {
            this._defineDatas.removeDefineDatas(defines);
        }
        hasDefine(define) {
            return this._defineDatas.has(define);
        }
        clearDefine() {
            this._defineDatas.clear();
        }
        clearData() {
            for (const key in this._data) {
                if (this._data[key] instanceof Laya.Resource) {
                    this._data[key]._removeReference();
                }
            }
            this._uniformBuffersPropertyMap.clear();
            this._uniformBuffers.forEach(buffer => {
                buffer.destroy();
            });
            this._uniformBuffers.clear();
            this._subUniformBuffers.forEach(buffer => {
                buffer.destroy();
            });
            this._subUniformBuffers.clear();
            this._data = {};
            this._gammaColorMap.clear();
            this.clearDefine();
            this._needCacheData = false;
            this._subUboBufferNumber = 0;
            this.renderState.setNull();
        }
        getBool(index) {
            return this._data[index];
        }
        setBool(index, value) {
            this._data[index] = value;
            if (this._needCacheData) ;
            this._checkRenderState(index);
        }
        getInt(index) {
            return this._data[index];
        }
        setInt(index, value) {
            this._data[index] = value;
            if (this._needCacheData) {
                this._updateCacheArray[index] = WebGLUniformBufferBase.prototype.setInt;
            }
            this._checkRenderState(index);
        }
        getNumber(index) {
            return this._data[index];
        }
        setNumber(index, value) {
            this._data[index] = value;
            if (this._needCacheData) {
                this._updateCacheArray[index] = WebGLUniformBufferBase.prototype.setFloat;
            }
            this._checkRenderState(index);
        }
        getVector2(index) {
            return this._data[index];
        }
        setVector2(index, value) {
            if (this._data[index]) {
                value.cloneTo(this._data[index]);
            }
            else
                this._data[index] = value.clone();
            if (this._needCacheData) {
                this._updateCacheArray[index] = WebGLUniformBufferBase.prototype.setVector2;
            }
        }
        getVector3(index) {
            return this._data[index];
        }
        setVector3(index, value) {
            if (this._data[index]) {
                value.cloneTo(this._data[index]);
            }
            else
                this._data[index] = value.clone();
            if (this._needCacheData) {
                this._updateCacheArray[index] = WebGLUniformBufferBase.prototype.setVector3;
            }
        }
        getVector(index) {
            return this._data[index];
        }
        setVector(index, value) {
            if (this._data[index]) {
                value.cloneTo(this._data[index]);
            }
            else
                this._data[index] = value.clone();
            if (this._needCacheData) {
                this._updateCacheArray[index] = WebGLUniformBufferBase.prototype.setVector4;
            }
        }
        getColor(index) {
            return this._gammaColorMap.get(index);
        }
        setColor(index, value) {
            if (!value)
                return;
            if (this._data[index]) {
                let gammaColor = this._gammaColorMap.get(index);
                value.cloneTo(gammaColor);
                let linearColor = this._data[index];
                linearColor.x = Laya.Color.gammaToLinearSpace(value.r);
                linearColor.y = Laya.Color.gammaToLinearSpace(value.g);
                linearColor.z = Laya.Color.gammaToLinearSpace(value.b);
                linearColor.w = value.a;
            }
            else {
                let linearColor = new Laya.Vector4();
                linearColor.x = Laya.Color.gammaToLinearSpace(value.r);
                linearColor.y = Laya.Color.gammaToLinearSpace(value.g);
                linearColor.z = Laya.Color.gammaToLinearSpace(value.b);
                linearColor.w = value.a;
                this._data[index] = linearColor;
                this._gammaColorMap.set(index, value.clone());
            }
            if (this._needCacheData) {
                this._updateCacheArray[index] = WebGLUniformBufferBase.prototype.setVector4;
            }
        }
        getLinearColor(index) {
            return this._data[index];
        }
        getMatrix4x4(index) {
            return this._data[index];
        }
        setMatrix4x4(index, value) {
            if (this._data[index]) {
                value.cloneTo(this._data[index]);
            }
            else {
                this._data[index] = value.clone();
            }
            if (this._needCacheData)
                this._updateCacheArray[index] = WebGLUniformBufferBase.prototype.setMatrix4x4;
        }
        getMatrix3x3(index) {
            return this._data[index];
        }
        setMatrix3x3(index, value) {
            if (this._data[index]) {
                value.cloneTo(this._data[index]);
            }
            else {
                this._data[index] = value.clone();
            }
            if (this._needCacheData) {
                this._updateCacheArray[index] = WebGLUniformBufferBase.prototype.setMatrix3x3;
            }
        }
        getBuffer(index) {
            return this._data[index];
        }
        setBuffer(index, value) {
            this._data[index] = value;
            if (this._needCacheData) {
                this._updateCacheArray[index] = WebGLUniformBufferBase.prototype.setArrayBuffer;
            }
        }
        setTexture(index, value) {
            var lastValue = this._data[index];
            if (value) {
                let shaderDefine = WebGLEngine._texGammaDefine[index];
                if (shaderDefine && value && value.gammaCorrection > 1) {
                    this.addDefine(shaderDefine);
                }
                else {
                    shaderDefine && this.removeDefine(shaderDefine);
                }
            }
            this._data[index] = value;
            lastValue && lastValue._removeReference();
            value && value._addReference();
        }
        _setInternalTexture(index, value) {
            this._data[index];
            if (value) {
                let shaderDefine = WebGLEngine._texGammaDefine[index];
                if (shaderDefine && value && value.gammaCorrection > 1) {
                    this.addDefine(shaderDefine);
                }
                else {
                    shaderDefine && this.removeDefine(shaderDefine);
                }
            }
            this._data[index] = value;
        }
        uploadCache() {
            let uploaded = false;
            for (let i in this._updateCacheArray) {
                uploaded = true;
                let index = parseInt(i);
                let ubo = this._uniformBuffersPropertyMap.get(index);
                if (ubo) {
                    this._updateCacheArray[i].call(ubo, index, this._data[index]);
                }
            }
            if (uploaded) {
                this._updateCacheArray = {};
            }
        }
        update(name) {
            if (Laya.Config._uniformBlock) {
                let unifomrMap = Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap(name);
                let uniformBuffer = this.createSubUniformBuffer(name, name, unifomrMap._idata);
                if (uniformBuffer) {
                    uniformBuffer.upload();
                }
            }
        }
        getTexture(index) {
            return this._data[index];
        }
        getSourceIndex(value) {
            for (var i in this._data) {
                if (this._data[i] == value)
                    return Number(i);
            }
            return -1;
        }
        cloneTo(destObject) {
            destObject.clearData();
            var destData = destObject._data;
            for (var k in this._data) {
                var value = this._data[k];
                if (value != null) {
                    if (typeof value == "number") {
                        destData[k] = value;
                    }
                    else if (typeof value == "boolean") {
                        destData[k] = value;
                    }
                    else if (value instanceof Laya.Vector2) {
                        let v2 = destData[k] || (destData[k] = new Laya.Vector2());
                        value.cloneTo(v2);
                    }
                    else if (value instanceof Laya.Vector3) {
                        let v3 = destData[k] || (destData[k] = new Laya.Vector3());
                        value.cloneTo(v3);
                    }
                    else if (value instanceof Laya.Vector4) {
                        let color = this.getColor(parseInt(k));
                        if (color) {
                            let clonecolor = color.clone();
                            destObject.setColor(parseInt(k), clonecolor);
                        }
                        else {
                            let v4 = destData[k] || (destData[k] = new Laya.Vector4());
                            value.cloneTo(v4);
                        }
                    }
                    else if (value instanceof Laya.Matrix3x3) {
                        let mat = destData[k] || (destData[k] = new Laya.Matrix3x3());
                        value.cloneTo(mat);
                    }
                    else if (value instanceof Laya.Matrix4x4) {
                        let mat = destData[k] || (destData[k] = new Laya.Matrix4x4());
                        value.cloneTo(mat);
                    }
                    else if (value instanceof Laya.Resource) {
                        destData[k] = value;
                        value._addReference();
                    }
                }
            }
            this._defineDatas.cloneTo(destObject._defineDatas);
            this._gammaColorMap.forEach((color, index) => {
                destObject._gammaColorMap.set(index, color.clone());
            });
        }
        getDefineData() {
            return this._defineDatas;
        }
        clone() {
            var dest = new WebGLShaderData();
            this.cloneTo(dest);
            return dest;
        }
        destroy() {
            if (this.destroyed) {
                return;
            }
            this.clearData();
            this._defineDatas.destroy();
            this._defineDatas = null;
            this.destroyed = true;
        }
    }
    WebGLShaderData.pointerCount = 0;

    class WebShaderPass {
        get renderState() {
            return this._renderState;
        }
        set renderState(value) {
            this._renderState = value;
        }
        get validDefine() {
            return this._validDefine;
        }
        set validDefine(value) {
            this._validDefine = value;
        }
        constructor(pass) {
            this._cacheShaderHierarchy = 1;
            this._cacheSharders = {};
            this._renderState = new Laya.RenderState();
            this._renderState.setNull();
        }
        _resizeCacheShaderMap(cacheMap, hierarchy, resizeLength) {
            var end = this._cacheShaderHierarchy - 1;
            if (hierarchy == end) {
                for (var k in cacheMap) {
                    var shader = cacheMap[k];
                    for (var i = 0, n = resizeLength - end; i < n; i++) {
                        if (i === n - 1)
                            cacheMap[0] = shader;
                        else
                            cacheMap = cacheMap[i == 0 ? k : 0] = {};
                    }
                }
            }
            else {
                ++hierarchy;
                for (var k in cacheMap)
                    this._resizeCacheShaderMap(cacheMap[k], hierarchy, resizeLength);
            }
        }
        setCacheShader(compileDefine, shader) {
            var cacheShaders = this._cacheSharders;
            var mask = compileDefine._mask;
            var endIndex = compileDefine._length - 1;
            var maxEndIndex = this._cacheShaderHierarchy - 1;
            for (var i = 0; i < maxEndIndex; i++) {
                var subMask = endIndex < i ? 0 : mask[i];
                var subCacheShaders = cacheShaders[subMask];
                (subCacheShaders) || (cacheShaders[subMask] = subCacheShaders = {});
                cacheShaders = subCacheShaders;
            }
            var cacheKey = endIndex < maxEndIndex ? 0 : mask[maxEndIndex];
            cacheShaders[cacheKey] = shader;
        }
        getCacheShader(compileDefine) {
            compileDefine._intersectionDefineDatas(this._validDefine);
            var cacheShaders = this._cacheSharders;
            var maskLength = compileDefine._length;
            if (maskLength > this._cacheShaderHierarchy) {
                this._resizeCacheShaderMap(cacheShaders, 0, maskLength);
                this._cacheShaderHierarchy = maskLength;
            }
            var mask = compileDefine._mask;
            var endIndex = compileDefine._length - 1;
            var maxEndIndex = this._cacheShaderHierarchy - 1;
            for (var i = 0; i < maxEndIndex; i++) {
                var subMask = endIndex < i ? 0 : mask[i];
                var subCacheShaders = cacheShaders[subMask];
                (subCacheShaders) || (cacheShaders[subMask] = subCacheShaders = {});
                cacheShaders = subCacheShaders;
            }
            var cacheKey = endIndex < maxEndIndex ? 0 : mask[maxEndIndex];
            var shader = cacheShaders[cacheKey];
            return shader;
        }
        destroy() {
        }
    }

    class WebSubShader {
        setUniformMap(_uniformMap) {
        }
        destroy() {
            throw new Laya.NotImplementedError();
        }
        addShaderPass(pass) { }
    }

    class WebUnitRenderModuleDataFactory {
        createSubShader() {
            return new WebSubShader();
        }
        createShaderPass(pass) {
            return new WebShaderPass(pass);
        }
        createRenderState() {
            return new Laya.RenderState();
        }
        createDefineDatas() {
            return new WebDefineDatas();
        }
    }
    Laya.Laya.addBeforeInitCallback(() => {
        if (!Laya.LayaGL.unitRenderModuleDataFactory)
            Laya.LayaGL.unitRenderModuleDataFactory = new WebUnitRenderModuleDataFactory();
    });

    class WebGLSetRendertarget2DCMD extends Laya.SetRendertarget2DCMD {
        constructor() {
            super();
            this.type = Laya.RenderCMDType.ChangeRenderTarget;
            this._clearColorValue = new Laya.Color();
        }
        apply(context) {
            if (this.rt)
                context.invertY = this.invertY;
            else
                context.invertY = false;
            let targetHeight = this.rt ? this.size.y : Laya.RenderState2D.height;
            let vpY = context.invertY ? this.viewportY : targetHeight - this.viewportY - this.size.y;
            context.setOffscreenView(this.size.x, this.size.y, this.viewportX, vpY);
            context.setRenderTarget(this.rt, this.clearColor, this.clearColorValue);
            context.passData.setVector2(Laya.ShaderDefines2D.UNIFORM_SIZE, this.size);
        }
    }
    class WebGLDraw2DElementCMD extends Laya.Draw2DElementCMD {
        constructor() {
            super();
            this.type = Laya.RenderCMDType.DrawElement;
        }
        setRenderelements(value) {
            this._elements = value;
        }
        apply(context) {
            if (this._elements.length == 1) {
                context.drawRenderElementOne(this._elements[0]);
            }
            else {
                this._elements.forEach(element => {
                    context.drawRenderElementOne(element);
                });
            }
        }
    }
    class WebGLBlit2DQuadCMD extends Laya.Blit2DQuadCMD {
        static _init_() {
            WebGLBlit2DQuadCMD.SCREENTEXTURE_ID = Laya.Shader3D.propertyNameToID("u_MainTex");
            WebGLBlit2DQuadCMD.SCREENTEXTUREOFFSETSCALE_ID = Laya.Shader3D.propertyNameToID("u_OffsetScale");
            WebGLBlit2DQuadCMD.MAINTEXTURE_TEXELSIZE_ID = Laya.Shader3D.propertyNameToID("u_MainTex_TexelSize");
            WebGLBlit2DQuadCMD.GammaCorrect = Laya.Shader3D.getDefineByName("GAMMACORRECT");
        }
        constructor() {
            super();
            if (!WebGLBlit2DQuadCMD.SCREENTEXTURE_ID) {
                WebGLBlit2DQuadCMD._init_();
            }
            this.type = Laya.RenderCMDType.Blit;
            this._offsetScale = new Laya.Vector4();
            this._sourceTexelSize = new Laya.Vector4();
        }
        set source(value) {
            this._source = value;
            if (this._source) {
                this._sourceTexelSize.setValue(1.0 / this._source.width, 1.0 / this._source.height, this._source.width, this._source.height);
            }
        }
        apply(context) {
            let dest = this._dest || context._destRT;
            if (!dest || dest._textures[0].gammaCorrection != 1) {
                this.element.materialShaderData.addDefine(WebGLBlit2DQuadCMD.GammaCorrect);
            }
            else {
                this.element.materialShaderData.removeDefine(WebGLBlit2DQuadCMD.GammaCorrect);
            }
            if (!dest) {
                context.invertY = false;
            }
            this.element.materialShaderData._setInternalTexture(WebGLBlit2DQuadCMD.SCREENTEXTURE_ID, this._source);
            this.element.materialShaderData.setVector(WebGLBlit2DQuadCMD.SCREENTEXTUREOFFSETSCALE_ID, this._offsetScale);
            this.element.materialShaderData.setVector(WebGLBlit2DQuadCMD.MAINTEXTURE_TEXELSIZE_ID, this._sourceTexelSize);
            context.setRenderTarget(this._dest, false, Laya.Color.BLACK);
            context.drawRenderElementOne(this.element);
        }
    }

    class Pass2DCacheInfo {
        constructor() {
            this.shaderInss = [];
            this.cacheFlagX = -1;
            this.cacheFlagY = -1;
            this.cachedDirtyVersion = -1;
            this.passDefineFlag = new Laya.Vector2(-1, -1);
        }
    }
    class WebGLRenderElement2D {
        constructor() {
            this.renderStateIsBySprite = true;
            this.type = 0;
            this._defineChangeFlag = new Laya.Vector2(-1, -1);
            this._dirtyVersion = 0;
            this._passCache = new Map();
        }
        get subShader() { return this._subShader; }
        set subShader(value) {
            if (this._subShader !== value) {
                this._subShader = value;
                this._dirtyVersion++;
            }
        }
        get materialShaderData() { return this._materialShaderData; }
        set materialShaderData(value) {
            if (this._materialShaderData !== value) {
                this._unregisterDefineFlag(this._materialShaderData);
                this._materialShaderData = value;
                this._registerDefineFlag(value);
                this._dirtyVersion++;
            }
        }
        get value2DShaderData() { return this._value2DShaderData; }
        set value2DShaderData(value) {
            if (this._value2DShaderData !== value) {
                this._unregisterDefineFlag(this._value2DShaderData);
                this._value2DShaderData = value;
                this._registerDefineFlag(value);
                this._dirtyVersion++;
            }
        }
        get globalShaderData() { return this._globalShaderData; }
        set globalShaderData(value) {
            if (this._globalShaderData !== value) {
                this._unregisterDefineFlag(this._globalShaderData);
                this._globalShaderData = value;
                this._registerDefineFlag(value);
                this._dirtyVersion++;
            }
        }
        _registerDefineFlag(data) {
            var _a;
            (_a = data === null || data === void 0 ? void 0 : data._defineDatas) === null || _a === void 0 ? void 0 : _a.addChangeFlagInfo(this._defineChangeFlag);
        }
        _unregisterDefineFlag(data) {
            var _a;
            (_a = data === null || data === void 0 ? void 0 : data._defineDatas) === null || _a === void 0 ? void 0 : _a.removeChangeFlagInfo(this._defineChangeFlag);
        }
        _getOrCreateCacheEntry(context) {
            let pd = context.passData || null;
            let arr = this._passCache.get(pd);
            if (!arr) {
                arr = [null, null, null, null];
                this._passCache.set(pd, arr);
            }
            let gamma = !context._destRT || context._destRT._textures[0].gammaCorrection != 1;
            let idx = (context.invertY ? 2 : 0) | (gamma ? 1 : 0);
            let entry = arr[idx];
            if (!entry) {
                entry = new Pass2DCacheInfo();
                if (pd === null || pd === void 0 ? void 0 : pd._defineDatas) {
                    pd._defineDatas.addChangeFlagInfo(entry.passDefineFlag);
                    entry.trackedPassData = pd;
                }
                arr[idx] = entry;
            }
            return entry;
        }
        _compileShader(context) {
            var passes = this._subShader._passes;
            let entry = this._curCacheEntry;
            let renderCount = 0;
            for (var j = 0, m = passes.length; j < m; j++) {
                var pass = passes[j];
                if (pass.pipelineMode !== context.pipelineMode)
                    continue;
                var comDef = WebGLRenderElement2D._compileDefine;
                if (this._globalShaderData) {
                    this._globalShaderData._defineDatas.cloneTo(comDef);
                }
                else {
                    context._globalConfigShaderData.cloneTo(comDef);
                }
                if (context.passData) {
                    comDef.addDefineDatas(context.passData._defineDatas);
                }
                let returnGamma = !(context._destRT) || ((context._destRT)._textures[0].gammaCorrection != 1);
                if (returnGamma) {
                    comDef.add(Laya.ShaderDefines2D.GAMMASPACE);
                }
                else {
                    comDef.remove(Laya.ShaderDefines2D.GAMMASPACE);
                }
                if (context.invertY) {
                    comDef.add(Laya.ShaderDefines2D.INVERTY);
                }
                else {
                    comDef.remove(Laya.ShaderDefines2D.INVERTY);
                }
                if (this._value2DShaderData) {
                    comDef.addDefineDatas(this._value2DShaderData.getDefineData());
                    pass.nodeCommonMap = this.nodeCommonMap;
                }
                if (this._materialShaderData)
                    comDef.addDefineDatas(this._materialShaderData._defineDatas);
                var shaderIns = pass.withCompile(comDef, true);
                entry.shaderInss[renderCount++] = shaderIns;
            }
            entry.shaderInss.length = renderCount;
        }
        _prepare(context) {
            this.globalShaderData = this.owner && this.owner._globalShaderData;
            let entry = this._getOrCreateCacheEntry(context);
            this._curCacheEntry = entry;
            let cfx = entry.cacheFlagX, cfy = entry.cacheFlagY;
            let dcf = this._defineChangeFlag;
            let pdf = entry.passDefineFlag;
            if (entry.cachedDirtyVersion !== this._dirtyVersion
                || dcf.x > cfx || (dcf.x === cfx && dcf.y > cfy)
                || pdf.x > cfx || (pdf.x === cfx && pdf.y > cfy)) {
                entry.cachedDirtyVersion = this._dirtyVersion;
                entry.cacheFlagX = Laya.Stat.loopCount;
                entry.cacheFlagY = WebGLEngine.instance._framePassCount;
                this._compileShader(context);
            }
        }
        _render(context) {
            context._prevTypeKey = -1;
            context._prevTextureKey = -1;
            context._prevClip = null;
            context._prevShaderIns = null;
            let inss = this._curCacheEntry.shaderInss;
            let count = inss.length;
            if (count === 1) {
                this.renderByShaderInstance(inss[0], context);
            }
            else {
                for (let j = 0; j < count; j++) {
                    this.renderByShaderInstance(inss[j], context);
                }
            }
        }
        _uploadGlobalAndPass(shader, context) {
            this._globalShaderData && shader.uploadUniforms(shader._cameraUniformParamsMap, this._globalShaderData, true);
            context.passData && shader.uploadUniforms(shader._sceneUniformParamsMap, context.passData, true);
        }
        renderByShaderInstance(shader, context) {
            if (!shader.complete || !this.geometry)
                return;
            shader.bind();
            this._uploadGlobalAndPass(shader, context);
            this._value2DShaderData && shader.uploadUniforms(shader._sprite2DUniformParamsMap, this._value2DShaderData, true);
            this._materialShaderData && shader.uploadUniforms(shader._materialUniformParamsMap, this._materialShaderData, true);
            if (this.renderStateIsBySprite || !this._materialShaderData) {
                shader.uploadRenderStateBlendDepth(this._value2DShaderData);
                shader.uploadRenderStateFrontFace(this._value2DShaderData, false, context.invertY);
            }
            else {
                shader.uploadRenderStateBlendDepth(this._materialShaderData);
                shader.uploadRenderStateFrontFace(this._materialShaderData, false, context.invertY);
            }
            WebGLEngine.instance.getDrawContext().drawGeometryElement(this.geometry);
        }
        destroy() {
            this._unregisterDefineFlag(this._globalShaderData);
            this._unregisterDefineFlag(this._materialShaderData);
            this._unregisterDefineFlag(this._value2DShaderData);
            if (this._passCache) {
                this._passCache.forEach(arr => {
                    var _a, _b;
                    for (let i = 0; i < 4; i++) {
                        let entry = arr[i];
                        if (entry) {
                            (_b = (_a = entry.trackedPassData) === null || _a === void 0 ? void 0 : _a._defineDatas) === null || _b === void 0 ? void 0 : _b.removeChangeFlagInfo(entry.passDefineFlag);
                        }
                    }
                });
            }
            this._globalShaderData = null;
            this._materialShaderData = null;
            this._value2DShaderData = null;
            this._passCache = null;
            this._curCacheEntry = null;
        }
    }
    WebGLRenderElement2D._compileDefine = new WebDefineDatas();

    class WebGLPrimitiveRenderElement2D extends WebGLRenderElement2D {
        constructor() {
            super(...arguments);
            this.typeKey = 0;
            this.textureKey = 0;
        }
        get primitiveShaderData() { return this._primitiveShaderData; }
        set primitiveShaderData(value) {
            if (this._primitiveShaderData !== value) {
                this._unregisterDefineFlag(this._primitiveShaderData);
                this._primitiveShaderData = value;
                this._registerDefineFlag(value);
                this._dirtyVersion++;
            }
        }
        _compileShader(context) {
            var passes = this.subShader._passes;
            let entry = this._curCacheEntry;
            let renderCount = 0;
            for (var j = 0, m = passes.length; j < m; j++) {
                var pass = passes[j];
                if (pass.pipelineMode !== context.pipelineMode)
                    continue;
                var comDef = WebGLRenderElement2D._compileDefine;
                if (this.globalShaderData) {
                    this.globalShaderData._defineDatas.cloneTo(comDef);
                }
                else {
                    context._globalConfigShaderData.cloneTo(comDef);
                }
                if (context.passData) {
                    comDef.addDefineDatas(context.passData._defineDatas);
                }
                let returnGamma = !(context._destRT) || ((context._destRT)._textures[0].gammaCorrection != 1);
                if (returnGamma) {
                    comDef.add(Laya.ShaderDefines2D.GAMMASPACE);
                }
                else {
                    comDef.remove(Laya.ShaderDefines2D.GAMMASPACE);
                }
                if (context.invertY) {
                    comDef.add(Laya.ShaderDefines2D.INVERTY);
                }
                else {
                    comDef.remove(Laya.ShaderDefines2D.INVERTY);
                }
                if (this.value2DShaderData) {
                    comDef.addDefineDatas(this.value2DShaderData.getDefineData());
                    pass.nodeCommonMap = this.nodeCommonMap;
                }
                if (this.materialShaderData)
                    comDef.addDefineDatas(this.materialShaderData._defineDatas);
                if (this._primitiveShaderData) {
                    pass.additionShaderData = WebGLPrimitiveRenderElement2D._additionShaderData;
                    comDef.addDefineDatas(this._primitiveShaderData.getDefineData());
                }
                var shaderIns = pass.withCompile(comDef, true);
                entry.shaderInss[renderCount++] = shaderIns;
            }
            entry.shaderInss.length = renderCount;
        }
        _render(context) {
            let inss = this._curCacheEntry.shaderInss;
            let count = inss.length;
            if (count === 1) {
                let shaderIns = inss[0];
                let clipInfo = this.owner.getClipInfo();
                if (this.owner.renderType === context._prevRenderType
                    && this.typeKey === context._prevTypeKey
                    && this.textureKey === context._prevTextureKey
                    && clipInfo === context._prevClip
                    && shaderIns === context._prevShaderIns) {
                    WebGLEngine.instance.getDrawContext().drawGeometryElement(this.geometry);
                }
                else {
                    this.renderByShaderInstance(shaderIns, context);
                }
                context._prevTypeKey = this.typeKey;
                context._prevTextureKey = this.textureKey;
                context._prevClip = clipInfo;
                context._prevShaderIns = shaderIns;
            }
            else {
                for (let j = 0; j < count; j++) {
                    this.renderByShaderInstance(inss[j], context);
                }
            }
        }
        renderByShaderInstance(shader, context) {
            if (!shader.complete || !this.geometry)
                return;
            shader.bind();
            this._uploadGlobalAndPass(shader, context);
            this.value2DShaderData && shader.uploadUniforms(shader._sprite2DUniformParamsMap, this.value2DShaderData, true);
            this.materialShaderData && shader.uploadUniforms(shader._materialUniformParamsMap, this.materialShaderData, true);
            let encoder = shader._additionUniformParamsMaps.get("Sprite2DGraphics");
            encoder && this._primitiveShaderData && shader.uploadUniforms(encoder, this._primitiveShaderData, true);
            let shaderData = this.value2DShaderData;
            if (!this.renderStateIsBySprite) {
                if (this.materialShaderData) {
                    shaderData = this.materialShaderData;
                }
                else if (this._primitiveShaderData) {
                    shaderData = this._primitiveShaderData;
                }
            }
            shader.uploadRenderStateBlendDepth(shaderData);
            shader.uploadRenderStateFrontFace(shaderData, false, context.invertY);
            WebGLEngine.instance.getDrawContext().drawGeometryElement(this.geometry);
        }
        destroy() {
            this._unregisterDefineFlag(this._primitiveShaderData);
            this._primitiveShaderData = null;
            super.destroy();
        }
    }
    WebGLPrimitiveRenderElement2D._additionShaderData = ["Sprite2DGraphics"];

    class WebGLSetRenderData extends Laya.SetRenderDataCMD {
        get dataType() {
            return this._dataType;
        }
        set dataType(value) {
            this._dataType = value;
        }
        get propertyID() {
            return this._propertyID;
        }
        set propertyID(value) {
            this._propertyID = value;
        }
        get dest() {
            return this._dest;
        }
        set dest(value) {
            this._dest = value;
        }
        get value() {
            return this._value;
        }
        set value(value) {
            switch (this.dataType) {
                case Laya.ShaderDataType.Int:
                case Laya.ShaderDataType.Float:
                case Laya.ShaderDataType.Bool:
                    this.data_number = value;
                    this._value = this.data_number;
                    break;
                case Laya.ShaderDataType.Matrix4x4:
                    !this.data_mat && (this.data_mat = new Laya.Matrix4x4());
                    value.cloneTo(this.data_mat);
                    this._value = this.data_mat;
                    break;
                case Laya.ShaderDataType.Color:
                    !this.data_Color && (this.data_Color = new Laya.Color());
                    value.cloneTo(this.data_Color);
                    this._value = this.data_Color;
                    break;
                case Laya.ShaderDataType.Texture2D:
                    this._value = this.data_texture = value;
                    break;
                case Laya.ShaderDataType.Vector4:
                    !this.data_v4 && (this.data_v4 = new Laya.Vector4());
                    value.cloneTo(this.data_v4);
                    this._value = this.data_v4;
                    break;
                case Laya.ShaderDataType.Vector2:
                    !this.data_v2 && (this.data_v2 = new Laya.Vector2());
                    value.cloneTo(this.data_v2);
                    this._value = this.data_v2;
                    break;
                case Laya.ShaderDataType.Vector3:
                    !this.data_v3 && (this.data_v3 = new Laya.Vector3());
                    value.cloneTo(this.data_v3);
                    this._value = this.data_v3;
                    break;
                case Laya.ShaderDataType.Buffer:
                    this._value = this.data_Buffer = value;
                    break;
            }
        }
        constructor() {
            super();
            this.type = Laya.RenderCMDType.ChangeData;
        }
        apply(context) {
            switch (this.dataType) {
                case Laya.ShaderDataType.Int:
                    this.dest.setInt(this.propertyID, this.value);
                    break;
                case Laya.ShaderDataType.Float:
                    this.dest.setNumber(this.propertyID, this.value);
                    break;
                case Laya.ShaderDataType.Bool:
                    this.dest.setBool(this.propertyID, this.value);
                    break;
                case Laya.ShaderDataType.Matrix4x4:
                    this.dest.setMatrix4x4(this.propertyID, this.value);
                    break;
                case Laya.ShaderDataType.Color:
                    this.dest.setColor(this.propertyID, this.value);
                    break;
                case Laya.ShaderDataType.Texture2D:
                    this.dest.setTexture(this.propertyID, this.value);
                    break;
                case Laya.ShaderDataType.Vector4:
                    this.dest.setVector(this.propertyID, this.value);
                    break;
                case Laya.ShaderDataType.Vector2:
                    this.dest.setVector2(this.propertyID, this.value);
                    break;
                case Laya.ShaderDataType.Vector3:
                    this.dest.setVector3(this.propertyID, this.value);
                    break;
                case Laya.ShaderDataType.Buffer:
                    this.dest.setBuffer(this.propertyID, this.value);
                    break;
            }
        }
    }
    class WebGLSetShaderDefine extends Laya.SetShaderDefineCMD {
        get define() {
            return this._define;
        }
        set define(value) {
            this._define = value;
        }
        get dest() {
            return this._dest;
        }
        set dest(value) {
            this._dest = value;
        }
        get add() {
            return this._add;
        }
        set add(value) {
            this._add = value;
        }
        constructor() {
            super();
            this.type = Laya.RenderCMDType.ChangeShaderDefine;
        }
        apply(context) {
            if (this.add) {
                this._dest.addDefine(this.define);
            }
            else {
                this._dest.removeDefine(this.define);
            }
        }
    }

    class WebglRenderContext2D {
        constructor() {
            this._clearColor = new Laya.Color(0, 0, 0, 0);
            this.invertY = false;
            this.pipelineMode = "Forward";
            this._prevTypeKey = -1;
            this._prevTextureKey = -1;
            this._prevClip = null;
            this._prevShaderIns = null;
            this._prevRenderType = -1;
            this._offscreenX = 0;
            this._offscreenY = 0;
            this._globalConfigShaderData = Laya.Shader3D._configDefineValues;
        }
        drawRenderElementList(list) {
            let time = performance.now();
            for (var i = 0, n = list.length; i < n; i++) {
                let element = list.elements[i];
                element._prepare(this);
            }
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_2DContextPre, performance.now() - time);
            time = performance.now();
            this.resetFastState();
            for (var i = 0, n = list.length; i < n; i++) {
                const element = list.elements[i];
                element._render(this);
                this._prevRenderType = element.owner ? element.owner.renderType : -1;
            }
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_2DDrawCall, list.length);
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_2DContextRender, performance.now() - time);
            Laya.LayaGL.renderEngine._framePassCount++;
            return 0;
        }
        setOffscreenView(width, height, x = 0, y = 0) {
            this._offscreenWidth = width;
            this._offscreenHeight = height;
            this._offscreenX = x;
            this._offscreenY = y;
        }
        getOffscreenView(out) {
            out.setValue(this._offscreenX, this._offscreenY, this._offscreenWidth, this._offscreenHeight);
        }
        resetFastState() {
            this._prevTypeKey = -1;
            this._prevTextureKey = -1;
            this._prevClip = null;
            this._prevShaderIns = null;
            this._prevRenderType = -1;
        }
        setRenderTarget(value, clear, clearColor) {
            this._destRT = value;
            clearColor.cloneTo(this._clearColor);
            if (this._destRT) {
                WebGLEngine.instance.getTextureContext().bindRenderTarget(this._destRT);
                WebGLEngine.instance.viewport(this._offscreenX, this._offscreenY, this._destRT._textures[0].width, this._destRT._textures[0].height);
            }
            else {
                WebGLEngine.instance.getTextureContext().bindoutScreenTarget();
                WebGLEngine.instance.viewport(this._offscreenX, this._offscreenY, this._offscreenWidth, this._offscreenHeight);
            }
            WebGLEngine.instance.scissorTest(false);
            WebGLEngine.instance.clearRenderTexture(clear ? Laya.RenderClearFlag.Color : Laya.RenderClearFlag.Nothing, this._clearColor);
        }
        getRenderTarget() {
            return this._destRT;
        }
        drawRenderElementOne(node) {
            node._prepare(this);
            node._render(this);
            this._prevRenderType = node.owner ? node.owner.renderType : -1;
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_2DDrawCall, 1);
            Laya.LayaGL.renderEngine._framePassCount++;
        }
        runOneCMD(cmd) {
            cmd.apply(this);
        }
        runCMDList(cmds) {
            cmds.forEach(element => {
                element.apply(this);
            });
        }
    }

    class WebGLRender2DProcess {
        constructor() {
        }
        createGraphic2DBufferBlock() {
            return new WebGraphics2DBufferBlock();
        }
        createGraphic2DVertexBlock() {
            return new WebGraphics2DVertexBlock();
        }
        create2DGraphicVertexDataView(wholeBuffer, elementOffset, elementSize, stride) {
            return new Web2DGraphic2DVertexDataView(wholeBuffer, elementOffset, elementSize, stride);
        }
        create2DGraphicIndexDataView(wholeBuffer, elementSize) {
            return new Web2DGraphic2DIndexDataView(wholeBuffer, elementSize);
        }
        create2DGraphicIndexBuffer() {
            return new Web2DGraphicsIndexBuffer();
        }
        createPrimitiveRenderElement2D() {
            return new WebGLPrimitiveRenderElement2D();
        }
        create2DGraphicVertexBuffer() {
            return new Web2DGraphicsVertexBuffer();
        }
        createRender2DPassManager() {
            return new WebRender2DPassManager();
        }
        create2DGlobalRenderDataHandle() {
            return new WebGlobalRenderData();
        }
        createSpineRenderDataHandle() {
            return new WebSpineRenderDataHandle();
        }
        create2D2DPrimitiveDataHandle() {
            return new WebPrimitiveDataHandle();
        }
        create2DBaseRenderDataHandle() {
            return new Web2DBaseRenderDataHandle();
        }
        createMesh2DRenderDataHandle() {
            return new WebMesh2DRenderDataHandle();
        }
        createSetRenderDataCMD() {
            return new WebGLSetRenderData();
        }
        createSetShaderDefineCMD() {
            return new WebGLSetShaderDefine();
        }
        createBlit2DQuadCMDData() {
            return new WebGLBlit2DQuadCMD();
        }
        createDraw2DElementCMDData() {
            return new WebGLDraw2DElementCMD();
        }
        createSetRendertarget2DCMD() {
            return new WebGLSetRendertarget2DCMD();
        }
        createRenderElement2D() {
            return new WebGLRenderElement2D();
        }
        createRenderContext2D() {
            return new WebglRenderContext2D();
        }
        createRender2DPass() {
            return new WebRender2DPass();
        }
        createRenderStruct2D() {
            return new WebRenderStruct2D();
        }
        createEmptyRenderDataHandle() {
            return new WebEmptyRender2DDataHandle();
        }
    }
    Laya.Laya.addBeforeInitCallback(() => {
        if (!Laya.LayaGL.render2DRenderPassFactory)
            Laya.LayaGL.render2DRenderPassFactory = new WebGLRender2DProcess();
    });

    class WebGLBufferState {
        constructor() {
            this._glVertexState = WebGLEngine.instance.createVertexState();
        }
        applyVertexBuffers() {
            this._glVertexState.applyVertexBuffer(this._vertexBuffers);
        }
        applyIndexBuffers() {
            this._glVertexState.applyIndexBuffer(this._bindedIndexBuffer);
        }
        applyState(vertexBuffers, indexBuffer) {
            this._vertexBuffers = vertexBuffers.slice();
            this._bindedIndexBuffer = indexBuffer;
            indexBuffer && indexBuffer._glBuffer.unbindBuffer();
            this.bind();
            this.applyVertexBuffers();
            this.applyIndexBuffers();
            this.unBind();
            indexBuffer && indexBuffer._glBuffer.unbindBuffer();
        }
        bind() {
            this._glVertexState.bindVertexArray();
            WebGLBufferState._curBindedBufferState = this;
        }
        unBind() {
            if (WebGLBufferState._curBindedBufferState == this) {
                this._glVertexState.unbindVertexArray();
                WebGLBufferState._curBindedBufferState = null;
            }
            else {
                throw new Error("BufferState: must call bind() function first.");
            }
        }
        isBind() {
            return (WebGLBufferState._curBindedBufferState == this);
        }
        destroy() {
            if (WebGLBufferState._curBindedBufferState == this) {
                this._glVertexState.unbindVertexArray();
                WebGLBufferState._curBindedBufferState = null;
            }
            this._glVertexState.destroy();
            this._vertexBuffers = null;
            this._bindedIndexBuffer = null;
        }
    }

    class WebGLCommandUniformMap extends Laya.CommandUniformMap {
        constructor(stateName) {
            super(stateName);
            this._idata = new Map();
            this._stateName = stateName;
            this._stateID = Laya.Shader3D.propertyNameToID(stateName);
        }
        hasPtrID(propertyID) {
            return this._stateID == propertyID || this._idata.has(propertyID);
        }
        addShaderUniform(propertyID, propertyKey, uniformtype, options) {
            this._idata.set(propertyID, { id: propertyID, uniformtype: uniformtype, propertyName: propertyKey, arrayLength: 0 });
        }
        addShaderUniformArray(propertyID, propertyName, uniformtype, arrayLength, block = "") {
            this._idata.set(propertyID, { id: propertyID, uniformtype: uniformtype, propertyName: propertyName, arrayLength: arrayLength });
        }
        setDefaultTextureData(key, defaultTex) {
        }
    }

    class WebGLConfig {
    }

    class WebGLIndexBuffer {
        constructor(targetType, bufferUsageType) {
            this._glBuffer = this._glBuffer = WebGLEngine.instance.createBuffer(targetType, bufferUsageType);
        }
        _setIndexDataLength(data) {
            var curBufSta = WebGLBufferState._curBindedBufferState;
            if (curBufSta) {
                curBufSta.unBind();
                this._glBuffer.bindBuffer();
                this._glBuffer.setDataLength(data);
                curBufSta.bind();
            }
            else {
                this._glBuffer.bindBuffer();
                this._glBuffer.setDataLength(data);
            }
        }
        setData(buffer, bufferOffset, dataStartIndex, dataCount) {
            let curBufSta = WebGLBufferState._curBindedBufferState;
            if (curBufSta) {
                curBufSta.unBind();
            }
            this._glBuffer.bindBuffer();
            var needSubData = dataStartIndex !== 0 || dataCount !== Number.MAX_SAFE_INTEGER;
            if (needSubData) {
                var subData = new Uint8Array(buffer, dataStartIndex, dataCount);
                this._glBuffer.setData(subData, bufferOffset);
            }
            else {
                this._glBuffer.setData(buffer, bufferOffset);
            }
            if (curBufSta)
                curBufSta.bind();
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_GeometryBufferUploadCount, 1);
        }
        _setIndexData(data, bufferOffset) {
            var curBufSta = WebGLBufferState._curBindedBufferState;
            if (curBufSta) {
                curBufSta.unBind();
                this._glBuffer.bindBuffer();
                this._glBuffer.setData(data, bufferOffset);
                curBufSta.bind();
            }
            else {
                this._glBuffer.bindBuffer();
                this._glBuffer.setData(data, bufferOffset);
            }
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_GeometryBufferUploadCount, 1);
        }
        destroy() {
            this._glBuffer.destroy();
        }
    }

    class WebGLRenderGeometryElement {
        get indexFormat() {
            return this._indexFormat;
        }
        set indexFormat(value) {
            this._indexFormat = value;
            this._glindexFormat = WebGLEngine.instance.getDrawContext().getIndexType(this._indexFormat);
        }
        get mode() {
            return this._mode;
        }
        set mode(value) {
            this._mode = value;
            this._glmode = WebGLEngine.instance.getDrawContext().getMeshTopology(this._mode);
        }
        constructor(mode, drawType) {
            this._id = ++WebGLRenderGeometryElement._idCounter;
            this.mode = mode;
            this.drawParams = new Laya.FastSinglelist();
            this.drawType = drawType;
        }
        getDrawDataParams(out) {
            out && this.drawParams.cloneTo(out);
        }
        setDrawArrayParams(first, count) {
            this.drawParams.add(first);
            this.drawParams.add(count);
        }
        setDrawElemenParams(count, offset) {
            this.drawParams.add(offset);
            this.drawParams.add(count);
        }
        destroy() {
            delete this.drawParams;
        }
        clearRenderParams() {
            this.drawParams.length = 0;
        }
        cloneTo(obj) {
            obj.mode = this.mode;
            obj.drawType = this.drawType;
            obj.indexFormat = this.indexFormat;
            obj.instanceCount = this.instanceCount;
            obj.drawParams.elements = this.drawParams.elements.slice();
            obj.drawParams.length = this.drawParams.length;
        }
    }
    WebGLRenderGeometryElement._idCounter = 0;

    class WebGLShaderInstance {
        constructor() {
            this._cacheShaerVariable = {};
            this._uploadMark = -1;
            this._uploadRenderType = -1;
            this.renderState = new Laya.RenderState();
            this._additionUniformParamsMaps = new Map();
            this._additionShaderData = new Map();
        }
        _serializeShader() {
            return null;
        }
        _deserialize(buffer) {
            return false;
        }
        get complete() {
            return this._renderShaderInstance._complete;
        }
        _create(shaderProcessInfo, shaderPass) {
            let useMaterial = Laya.Config.matUseUBO;
            Laya.Config.matUseUBO = (!shaderProcessInfo.is2D) && Laya.Config.matUseUBO;
            let shaderObj = Laya.GLSLCodeGenerator.GLShaderLanguageProcess3D(shaderProcessInfo.defineString, shaderProcessInfo.attributeMap, shaderProcessInfo.uniformMap, shaderProcessInfo.vs, shaderProcessInfo.ps);
            this._renderShaderInstance = WebGLEngine.instance.createShaderInstance(shaderObj.vs, shaderObj.fs, shaderProcessInfo.attributeMap);
            Laya.Config.matUseUBO = useMaterial;
            if (WebGLEngine._lastShaderError) {
                console.warn(`[ShaderCompile]Error compiling shader '${shaderPass._owner._owner.name}' (pipelineMode=${shaderPass.pipelineMode})\n`, WebGLEngine._lastShaderError);
            }
            if (this._renderShaderInstance._complete) {
                this._shaderPass = shaderPass.moduleData;
                shaderProcessInfo.is2D ? this._create2D() : this._create3D();
            }
        }
        _create3D() {
            this._sceneUniformParamsMap = new Laya.CommandEncoder();
            this._cameraUniformParamsMap = new Laya.CommandEncoder();
            this._spriteUniformParamsMap = new Laya.CommandEncoder();
            this._materialUniformParamsMap = new Laya.CommandEncoder();
            let context = Laya.WebGLRenderContext3D._instance;
            let preDrawUniforms = context.preDrawUniformMaps;
            let preDrawParams = [];
            for (let key of preDrawUniforms) {
                let params = Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap(key);
                preDrawParams.push(params);
            }
            const cameraParams = Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap("BaseCamera");
            let i, n;
            let data = this._renderShaderInstance.getUniformMap();
            for (i = 0, n = data.length; i < n; i++) {
                let one = data[i];
                if (preDrawParams.find((params) => {
                    return params.hasPtrID(one.dataOffset);
                })) {
                    this._sceneUniformParamsMap.addShaderUniform(one);
                }
                else if (cameraParams.hasPtrID(one.dataOffset)) {
                    this._cameraUniformParamsMap.addShaderUniform(one);
                }
                else if (this.hasSpritePtrID(one.dataOffset)) {
                    this._spriteUniformParamsMap.addShaderUniform(one);
                }
                else if (this._hasAdditionShaderData(one.dataOffset)) {
                    let str = this._hasAdditionShaderData(one.dataOffset);
                    if (!this._additionUniformParamsMaps.get(str)) {
                        let commandEncoder = new Laya.CommandEncoder();
                        this._additionUniformParamsMaps.set(str, commandEncoder);
                    }
                    this._additionUniformParamsMaps.get(str).addShaderUniform(one);
                }
                else {
                    this._materialUniformParamsMap.addShaderUniform(one);
                }
            }
        }
        _create2D() {
            this._sprite2DUniformParamsMap = new Laya.CommandEncoder();
            this._materialUniformParamsMap = new Laya.CommandEncoder();
            this._sceneUniformParamsMap = new Laya.CommandEncoder();
            this._cameraUniformParamsMap = new Laya.CommandEncoder();
            const passParms = Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap("Sprite2DPass");
            const globalParams = Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap("Sprite2DGlobal");
            let i, n;
            let data = this._renderShaderInstance.getUniformMap();
            for (i = 0, n = data.length; i < n; i++) {
                let one = data[i];
                if (this.hasSpritePtrID(one.dataOffset)) {
                    this._sprite2DUniformParamsMap.addShaderUniform(one);
                }
                else if (passParms.hasPtrID(one.dataOffset)) {
                    this._sceneUniformParamsMap.addShaderUniform(one);
                }
                else if (globalParams.hasPtrID(one.dataOffset)) {
                    this._cameraUniformParamsMap.addShaderUniform(one);
                }
                else if (this._hasAdditionShaderData(one.dataOffset)) {
                    let str = this._hasAdditionShaderData(one.dataOffset);
                    if (!this._additionUniformParamsMaps.get(str)) {
                        let commandEncoder = new Laya.CommandEncoder();
                        this._additionUniformParamsMaps.set(str, commandEncoder);
                    }
                    this._additionUniformParamsMaps.get(str).addShaderUniform(one);
                }
                else {
                    this._materialUniformParamsMap.addShaderUniform(one);
                }
            }
        }
        hasSpritePtrID(dataOffset) {
            let commap = this._shaderPass.nodeCommonMap;
            if (!commap) {
                return false;
            }
            else {
                for (let i = 0, n = commap.length; i < n; i++) {
                    if (Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap(commap[i]).hasPtrID(dataOffset))
                        return true;
                }
                return false;
            }
        }
        _hasAdditionShaderData(dataOffset) {
            let additionShaderData = this._shaderPass.additionShaderData;
            if (!additionShaderData) {
                return null;
            }
            else {
                for (let i = 0, n = additionShaderData.length; i < n; i++) {
                    if (Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap(additionShaderData[i]).hasPtrID(dataOffset))
                        return additionShaderData[i];
                }
            }
            return null;
        }
        _disposeResource() {
            this._renderShaderInstance.destroy();
            this._sceneUniformParamsMap = null;
            this._cameraUniformParamsMap = null;
            this._spriteUniformParamsMap = null;
            this._materialUniformParamsMap = null;
            this._sprite2DUniformParamsMap = null;
            this._uploadMaterial = null;
            this._uploadRender = null;
            this._uploadCameraShaderValue = null;
            this._uploadScene = null;
            this._additionShaderData = null;
            this.matRenderStateCache = null;
        }
        bind() {
            return this._renderShaderInstance.bind();
        }
        uploadUniforms(shaderUniform, shaderDatas, uploadUnTexture) {
            WebGLEngine.instance.uploadUniforms(this._renderShaderInstance, shaderUniform, shaderDatas, uploadUnTexture);
        }
        updateRenderState(renderState) {
            var _a, _b, _c, _d, _e, _f, _g, _h, _j, _k, _l, _m, _o, _p, _q, _r, _s, _t, _u, _v, _w, _x, _y, _z, _0;
            if (this._shaderPass.statefirst) {
                if (this.matRenderStateCache === renderState.hash) {
                    return;
                }
                const passState = this._shaderPass.renderState;
                this.renderState.cull = (_a = passState.cull) !== null && _a !== void 0 ? _a : renderState.cull;
                this.renderState.blend = (_b = passState.blend) !== null && _b !== void 0 ? _b : renderState.blend;
                this.renderState.srcBlend = (_c = passState.srcBlend) !== null && _c !== void 0 ? _c : renderState.srcBlend;
                this.renderState.dstBlend = (_d = passState.dstBlend) !== null && _d !== void 0 ? _d : renderState.dstBlend;
                this.renderState.depthTest = (_e = passState.depthTest) !== null && _e !== void 0 ? _e : renderState.depthTest;
                this.renderState.depthWrite = (_f = passState.depthWrite) !== null && _f !== void 0 ? _f : renderState.depthWrite;
                this.renderState.stencilTest = (_g = passState.stencilTest) !== null && _g !== void 0 ? _g : renderState.stencilTest;
                this.renderState.stencilWrite = (_h = passState.stencilWrite) !== null && _h !== void 0 ? _h : renderState.stencilWrite;
                const stencilOpX = (_j = passState.stencilOp.x) !== null && _j !== void 0 ? _j : renderState.stencilOp.x;
                const stencilOpY = (_k = passState.stencilOp.y) !== null && _k !== void 0 ? _k : renderState.stencilOp.y;
                const stencilOpZ = (_l = passState.stencilOp.z) !== null && _l !== void 0 ? _l : renderState.stencilOp.z;
                this.renderState.stencilOp.set(stencilOpX, stencilOpY, stencilOpZ);
                this.renderState.stencilRef = (_m = passState.stencilRef) !== null && _m !== void 0 ? _m : renderState.stencilRef;
                this.renderState.stencilReadMask = (_o = passState.stencilReadMask) !== null && _o !== void 0 ? _o : renderState.stencilReadMask;
                this.renderState.stencilWriteMask = (_p = passState.stencilWriteMask) !== null && _p !== void 0 ? _p : renderState.stencilWriteMask;
                this.renderState.blendEquation = (_q = passState.blendEquation) !== null && _q !== void 0 ? _q : renderState.blendEquation;
                this.renderState.blendEquationRGB = (_r = passState.blendEquationRGB) !== null && _r !== void 0 ? _r : renderState.blendEquationRGB;
                this.renderState.blendEquationAlpha = (_s = passState.blendEquationAlpha) !== null && _s !== void 0 ? _s : renderState.blendEquationAlpha;
                this.renderState.srcBlendRGB = (_t = passState.srcBlendRGB) !== null && _t !== void 0 ? _t : renderState.srcBlendRGB;
                this.renderState.dstBlendRGB = (_u = passState.dstBlendRGB) !== null && _u !== void 0 ? _u : renderState.dstBlendRGB;
                this.renderState.srcBlendAlpha = (_v = passState.srcBlendAlpha) !== null && _v !== void 0 ? _v : renderState.srcBlendAlpha;
                this.renderState.dstBlendAlpha = (_w = passState.dstBlendAlpha) !== null && _w !== void 0 ? _w : renderState.dstBlendAlpha;
                this.renderState.depthBias = (_x = passState.depthBias) !== null && _x !== void 0 ? _x : renderState.depthBias;
                this.renderState.depthBiasConstant = (_y = passState.depthBiasConstant) !== null && _y !== void 0 ? _y : renderState.depthBiasConstant;
                this.renderState.depthBiasSlopeScale = (_z = passState.depthBiasSlopeScale) !== null && _z !== void 0 ? _z : renderState.depthBiasSlopeScale;
                this.renderState.depthBiasClamp = (_0 = passState.depthBiasClamp) !== null && _0 !== void 0 ? _0 : renderState.depthBiasClamp;
                this.renderState.hash = WebGLEngine.instance.hashRenderState(this.renderState);
                this.matRenderStateCache = renderState.hash;
            }
        }
        uploadRenderState(renderState, isTarget, invertFront) {
            const engine = WebGLEngine.instance._GLRenderState;
            if (this._shaderPass.statefirst) {
                engine.setRenderState(this.renderState, isTarget, invertFront);
            }
            else {
                engine.setRenderState(renderState, isTarget, invertFront);
            }
        }
        uploadRenderStateBlendDepth(shaderDatas) {
            if ((this._shaderPass).statefirst)
                this.uploadRenderStateBlendDepthByShader(shaderDatas);
            else
                this.uploadRenderStateBlendDepthByMaterial(shaderDatas);
        }
        uploadRenderStateBlendDepthByShader(shaderDatas) {
            var _a, _b, _c, _d, _e, _f, _g, _h, _j, _k, _l, _m, _o, _p, _q, _r, _s, _t, _u, _v, _w, _x, _y, _z, _0, _1, _2, _3, _4, _5, _6, _7, _8, _9, _10, _11, _12, _13, _14, _15, _16, _17, _18, _19;
            const engineRenderState = WebGLEngine.instance._GLRenderState;
            var datas = shaderDatas._data;
            var renderState = (this._shaderPass).renderState;
            var depthWrite = (_b = ((_a = renderState.depthWrite) !== null && _a !== void 0 ? _a : datas[Laya.Shader3D.DEPTH_WRITE])) !== null && _b !== void 0 ? _b : Laya.RenderState.Default.depthWrite;
            engineRenderState.setDepthMask(depthWrite);
            var depthTest = (_d = ((_c = renderState.depthTest) !== null && _c !== void 0 ? _c : datas[Laya.Shader3D.DEPTH_TEST])) !== null && _d !== void 0 ? _d : Laya.RenderState.Default.depthTest;
            if (depthTest == Laya.RenderState.DEPTHTEST_OFF)
                engineRenderState.setDepthTest(false);
            else {
                engineRenderState.setDepthTest(true);
                engineRenderState.setDepthFunc(depthTest);
            }
            var stencilWrite = (_f = ((_e = renderState.stencilWrite) !== null && _e !== void 0 ? _e : datas[Laya.Shader3D.STENCIL_WRITE])) !== null && _f !== void 0 ? _f : Laya.RenderState.Default.stencilWrite;
            engineRenderState.setStencilWrite(stencilWrite);
            let stencilWriteMask = stencilWrite ? ((_h = ((_g = renderState.stencilWriteMask) !== null && _g !== void 0 ? _g : datas[Laya.Shader3D.STENCIL_WRITE_MASK])) !== null && _h !== void 0 ? _h : Laya.RenderState.Default.stencilWriteMask) : 0x00;
            engineRenderState.setStencilWriteMask(stencilWriteMask);
            if (stencilWrite) {
                var stencilOp = (_k = ((_j = renderState.stencilOp) !== null && _j !== void 0 ? _j : datas[Laya.Shader3D.STENCIL_Op])) !== null && _k !== void 0 ? _k : Laya.RenderState.Default.stencilOp;
                engineRenderState.setStencilOp(stencilOp.x, stencilOp.y, stencilOp.z);
            }
            var stencilTest = (_m = ((_l = renderState.stencilTest) !== null && _l !== void 0 ? _l : datas[Laya.Shader3D.STENCIL_TEST])) !== null && _m !== void 0 ? _m : Laya.RenderState.Default.stencilTest;
            if (stencilTest == Laya.RenderState.STENCILTEST_OFF) {
                engineRenderState.setStencilTest(false);
            }
            else {
                engineRenderState.setStencilTest(true);
                var stencilRef = (_p = ((_o = renderState.stencilRef) !== null && _o !== void 0 ? _o : datas[Laya.Shader3D.STENCIL_Ref])) !== null && _p !== void 0 ? _p : Laya.RenderState.Default.stencilRef;
                let stencilReadMask = (_r = ((_q = renderState.stencilReadMask) !== null && _q !== void 0 ? _q : datas[Laya.Shader3D.STENCIL_READ_MASK])) !== null && _r !== void 0 ? _r : Laya.RenderState.Default.stencilReadMask;
                engineRenderState.setStencilFunc(stencilTest, stencilRef, stencilReadMask);
            }
            let depthBias = (_t = (_s = renderState.depthBias) !== null && _s !== void 0 ? _s : datas[Laya.Shader3D.DEPTH_BIAS]) !== null && _t !== void 0 ? _t : Laya.RenderState.Default.depthBias;
            engineRenderState.setDepthBias(depthBias);
            if (depthBias) {
                let depthBiasConstant = (_v = ((_u = renderState.depthBiasConstant) !== null && _u !== void 0 ? _u : datas[Laya.Shader3D.DEPTH_BIAS_CONSTANT])) !== null && _v !== void 0 ? _v : Laya.RenderState.Default.depthBiasConstant;
                let depthBiasSlopeScale = (_x = ((_w = renderState.depthBiasSlopeScale) !== null && _w !== void 0 ? _w : datas[Laya.Shader3D.DEPTH_BIAS_SLOPESCALE])) !== null && _x !== void 0 ? _x : Laya.RenderState.Default.depthBiasSlopeScale;
                let depthBiasClamp = (_z = ((_y = renderState.depthBiasClamp) !== null && _y !== void 0 ? _y : datas[Laya.Shader3D.DEPTH_BIAS_CLAMP])) !== null && _z !== void 0 ? _z : Laya.RenderState.Default.depthBiasClamp;
                engineRenderState.setDepthBiasFactor(depthBiasConstant, depthBiasSlopeScale, depthBiasClamp);
            }
            var blend = (_1 = ((_0 = renderState.blend) !== null && _0 !== void 0 ? _0 : datas[Laya.Shader3D.BLEND])) !== null && _1 !== void 0 ? _1 : Laya.RenderState.Default.blend;
            switch (blend) {
                case Laya.RenderState.BLEND_DISABLE:
                    engineRenderState.setBlend(false);
                    break;
                case Laya.RenderState.BLEND_ENABLE_ALL:
                    var blendEquation = (_3 = ((_2 = renderState.blendEquation) !== null && _2 !== void 0 ? _2 : datas[Laya.Shader3D.BLEND_EQUATION])) !== null && _3 !== void 0 ? _3 : Laya.RenderState.Default.blendEquation;
                    var srcBlend = (_5 = ((_4 = renderState.srcBlend) !== null && _4 !== void 0 ? _4 : datas[Laya.Shader3D.BLEND_SRC])) !== null && _5 !== void 0 ? _5 : Laya.RenderState.Default.srcBlend;
                    var dstBlend = (_7 = ((_6 = renderState.dstBlend) !== null && _6 !== void 0 ? _6 : datas[Laya.Shader3D.BLEND_DST])) !== null && _7 !== void 0 ? _7 : Laya.RenderState.Default.dstBlend;
                    engineRenderState.setBlend(true);
                    engineRenderState.setBlendEquation(blendEquation);
                    engineRenderState.setBlendFunc(srcBlend, dstBlend);
                    break;
                case Laya.RenderState.BLEND_ENABLE_SEPERATE:
                    var blendEquationRGB = (_9 = ((_8 = renderState.blendEquationRGB) !== null && _8 !== void 0 ? _8 : datas[Laya.Shader3D.BLEND_EQUATION_RGB])) !== null && _9 !== void 0 ? _9 : Laya.RenderState.Default.blendEquationRGB;
                    var blendEquationAlpha = (_11 = ((_10 = renderState.blendEquationAlpha) !== null && _10 !== void 0 ? _10 : datas[Laya.Shader3D.BLEND_EQUATION_ALPHA])) !== null && _11 !== void 0 ? _11 : Laya.RenderState.Default.blendEquationAlpha;
                    var srcRGB = (_13 = ((_12 = renderState.srcBlendRGB) !== null && _12 !== void 0 ? _12 : datas[Laya.Shader3D.BLEND_SRC_RGB])) !== null && _13 !== void 0 ? _13 : Laya.RenderState.Default.srcBlendRGB;
                    var dstRGB = (_15 = ((_14 = renderState.dstBlendRGB) !== null && _14 !== void 0 ? _14 : datas[Laya.Shader3D.BLEND_DST_RGB])) !== null && _15 !== void 0 ? _15 : Laya.RenderState.Default.dstBlendRGB;
                    var srcAlpha = (_17 = ((_16 = renderState.srcBlendAlpha) !== null && _16 !== void 0 ? _16 : datas[Laya.Shader3D.BLEND_SRC_ALPHA])) !== null && _17 !== void 0 ? _17 : Laya.RenderState.Default.srcBlendAlpha;
                    var dstAlpha = (_19 = ((_18 = renderState.dstBlendAlpha) !== null && _18 !== void 0 ? _18 : datas[Laya.Shader3D.BLEND_DST_ALPHA])) !== null && _19 !== void 0 ? _19 : Laya.RenderState.Default.dstBlendAlpha;
                    engineRenderState.setBlend(true);
                    engineRenderState.setBlendEquationSeparate(blendEquationRGB, blendEquationAlpha);
                    engineRenderState.setBlendFuncSeperate(srcRGB, dstRGB, srcAlpha, dstAlpha);
                    break;
            }
        }
        uploadRenderStateBlendDepthByMaterial(shaderDatas) {
            var _a, _b, _c;
            const engineRenderState = WebGLEngine.instance._GLRenderState;
            var datas = shaderDatas.getData();
            var depthWrite = datas[Laya.Shader3D.DEPTH_WRITE];
            depthWrite = depthWrite !== null && depthWrite !== void 0 ? depthWrite : Laya.RenderState.Default.depthWrite;
            engineRenderState.setDepthMask(depthWrite);
            var depthTest = datas[Laya.Shader3D.DEPTH_TEST];
            depthTest = depthTest !== null && depthTest !== void 0 ? depthTest : Laya.RenderState.Default.depthTest;
            if (depthTest === Laya.RenderState.DEPTHTEST_OFF) {
                engineRenderState.setDepthTest(false);
            }
            else {
                engineRenderState.setDepthTest(true);
                engineRenderState.setDepthFunc(depthTest);
            }
            var stencilWrite = datas[Laya.Shader3D.STENCIL_WRITE];
            stencilWrite = stencilWrite !== null && stencilWrite !== void 0 ? stencilWrite : Laya.RenderState.Default.stencilWrite;
            engineRenderState.setStencilWrite(stencilWrite);
            let stencilWriteMask = stencilWrite ? ((_a = datas[Laya.Shader3D.STENCIL_WRITE_MASK]) !== null && _a !== void 0 ? _a : Laya.RenderState.Default.stencilWriteMask) : 0x00;
            engineRenderState.setStencilWriteMask(stencilWriteMask);
            if (stencilWrite) {
                var stencilOp = datas[Laya.Shader3D.STENCIL_Op];
                stencilOp = stencilOp !== null && stencilOp !== void 0 ? stencilOp : Laya.RenderState.Default.stencilOp;
                engineRenderState.setStencilOp(stencilOp.x, stencilOp.y, stencilOp.z);
            }
            var stencilTest = datas[Laya.Shader3D.STENCIL_TEST];
            stencilTest = stencilTest !== null && stencilTest !== void 0 ? stencilTest : Laya.RenderState.Default.stencilTest;
            if (stencilTest == Laya.RenderState.STENCILTEST_OFF) {
                engineRenderState.setStencilTest(false);
            }
            else {
                let stencilReadMask = (_b = datas[Laya.Shader3D.STENCIL_READ_MASK]) !== null && _b !== void 0 ? _b : Laya.RenderState.Default.stencilReadMask;
                var stencilRef = datas[Laya.Shader3D.STENCIL_Ref];
                stencilRef = stencilRef !== null && stencilRef !== void 0 ? stencilRef : Laya.RenderState.Default.stencilRef;
                engineRenderState.setStencilTest(true);
                engineRenderState.setStencilFunc(stencilTest, stencilRef, stencilReadMask);
            }
            let depthBias = (_c = datas[Laya.Shader3D.DEPTH_BIAS]) !== null && _c !== void 0 ? _c : Laya.RenderState.Default.depthBias;
            engineRenderState.setDepthBias(depthBias);
            if (depthBias) {
                let depthBiasConstant = datas[Laya.Shader3D.DEPTH_BIAS_CONSTANT];
                depthBiasConstant = depthBiasConstant !== null && depthBiasConstant !== void 0 ? depthBiasConstant : Laya.RenderState.Default.depthBiasConstant;
                let depthBiasSlopeScale = datas[Laya.Shader3D.DEPTH_BIAS_SLOPESCALE];
                depthBiasSlopeScale = depthBiasSlopeScale !== null && depthBiasSlopeScale !== void 0 ? depthBiasSlopeScale : Laya.RenderState.Default.depthBiasSlopeScale;
                let depthBiasClamp = datas[Laya.Shader3D.DEPTH_BIAS_CLAMP];
                depthBiasClamp = depthBiasClamp !== null && depthBiasClamp !== void 0 ? depthBiasClamp : Laya.RenderState.Default.depthBiasClamp;
                engineRenderState.setDepthBiasFactor(depthBiasConstant, depthBiasSlopeScale, depthBiasClamp);
            }
            var blend = datas[Laya.Shader3D.BLEND];
            blend = blend !== null && blend !== void 0 ? blend : Laya.RenderState.Default.blend;
            switch (blend) {
                case Laya.RenderState.BLEND_ENABLE_ALL:
                    var blendEquation = datas[Laya.Shader3D.BLEND_EQUATION];
                    blendEquation = blendEquation !== null && blendEquation !== void 0 ? blendEquation : Laya.RenderState.Default.blendEquation;
                    var srcBlend = datas[Laya.Shader3D.BLEND_SRC];
                    srcBlend = srcBlend !== null && srcBlend !== void 0 ? srcBlend : Laya.RenderState.Default.srcBlend;
                    var dstBlend = datas[Laya.Shader3D.BLEND_DST];
                    dstBlend = dstBlend !== null && dstBlend !== void 0 ? dstBlend : Laya.RenderState.Default.dstBlend;
                    engineRenderState.setBlend(true);
                    engineRenderState.setBlendEquation(blendEquation);
                    engineRenderState.setBlendFunc(srcBlend, dstBlend);
                    break;
                case Laya.RenderState.BLEND_ENABLE_SEPERATE:
                    var blendEquationRGB = datas[Laya.Shader3D.BLEND_EQUATION_RGB];
                    blendEquationRGB = blendEquationRGB !== null && blendEquationRGB !== void 0 ? blendEquationRGB : Laya.RenderState.Default.blendEquationRGB;
                    var blendEquationAlpha = datas[Laya.Shader3D.BLEND_EQUATION_ALPHA];
                    blendEquationAlpha = blendEquationAlpha !== null && blendEquationAlpha !== void 0 ? blendEquationAlpha : Laya.RenderState.Default.blendEquationAlpha;
                    var srcRGB = datas[Laya.Shader3D.BLEND_SRC_RGB];
                    srcRGB = srcRGB !== null && srcRGB !== void 0 ? srcRGB : Laya.RenderState.Default.srcBlendRGB;
                    var dstRGB = datas[Laya.Shader3D.BLEND_DST_RGB];
                    dstRGB = dstRGB !== null && dstRGB !== void 0 ? dstRGB : Laya.RenderState.Default.dstBlendRGB;
                    var srcAlpha = datas[Laya.Shader3D.BLEND_SRC_ALPHA];
                    srcAlpha = srcAlpha !== null && srcAlpha !== void 0 ? srcAlpha : Laya.RenderState.Default.srcBlendAlpha;
                    var dstAlpha = datas[Laya.Shader3D.BLEND_DST_ALPHA];
                    dstAlpha = dstAlpha !== null && dstAlpha !== void 0 ? dstAlpha : Laya.RenderState.Default.dstBlendAlpha;
                    engineRenderState.setBlend(true);
                    engineRenderState.setBlendEquationSeparate(blendEquationRGB, blendEquationAlpha);
                    engineRenderState.setBlendFuncSeperate(srcRGB, dstRGB, srcAlpha, dstAlpha);
                    break;
                case Laya.RenderState.BLEND_DISABLE:
                default:
                    engineRenderState.setBlend(false);
                    break;
            }
        }
        uploadRenderStateFrontFace(shaderDatas, isTarget, invertFront) {
            var _a;
            const engineRenderState = WebGLEngine.instance._GLRenderState;
            var renderState = (this._shaderPass).renderState;
            var datas = shaderDatas.getData();
            var cull = datas[Laya.Shader3D.CULL];
            if ((this._shaderPass).statefirst) {
                cull = (_a = renderState.cull) !== null && _a !== void 0 ? _a : cull;
            }
            cull = cull !== null && cull !== void 0 ? cull : Laya.RenderState.Default.cull;
            var forntFace;
            switch (cull) {
                case Laya.RenderState.CULL_NONE:
                    engineRenderState.setCullFace(false);
                    if (isTarget != invertFront)
                        forntFace = Laya.CullMode.Front;
                    else
                        forntFace = Laya.CullMode.Back;
                    engineRenderState.setFrontFace(forntFace);
                    break;
                case Laya.RenderState.CULL_FRONT:
                    engineRenderState.setCullFace(true);
                    if (isTarget == invertFront)
                        forntFace = Laya.CullMode.Front;
                    else
                        forntFace = Laya.CullMode.Back;
                    engineRenderState.setFrontFace(forntFace);
                    break;
                case Laya.RenderState.CULL_BACK:
                default:
                    engineRenderState.setCullFace(true);
                    if (isTarget != invertFront)
                        forntFace = Laya.CullMode.Front;
                    else
                        forntFace = Laya.CullMode.Back;
                    engineRenderState.setFrontFace(forntFace);
                    break;
            }
        }
    }

    class WebGLVertexBuffer {
        get vertexDeclaration() {
            return this._vertexDeclaration;
        }
        set vertexDeclaration(value) {
            this._vertexDeclaration = value;
            this._shaderValues = this._vertexDeclaration._shaderValues;
        }
        constructor(targetType, bufferUsageType) {
            this._glBuffer = WebGLEngine.instance.createBuffer(targetType, bufferUsageType);
        }
        getStorageBuffer() {
            return null;
        }
        setDataLength(byteLength) {
            this._glBuffer.setDataLength(byteLength);
        }
        setData(buffer, bufferOffset, dataStartIndex, dataCount) {
            this.bind();
            var needSubData = dataStartIndex !== 0 || dataCount !== Number.MAX_SAFE_INTEGER;
            if (needSubData) {
                var subData = new Uint8Array(buffer, dataStartIndex, dataCount);
                this._glBuffer.setData(subData, bufferOffset);
            }
            else {
                this._glBuffer.setData(buffer, bufferOffset);
            }
            Laya.LayaGL.statAgent.recordCTData(Laya.StatElement.CT_GeometryBufferUploadCount, 1);
        }
        bind() {
            return this._glBuffer.bindBuffer();
        }
        unbind() {
            return this._glBuffer.unbindBuffer();
        }
        orphanStorage() {
            this.bind();
            this._glBuffer.setDataLength(this._glBuffer._byteLength);
        }
        destroy() {
            this._glBuffer.destroy();
            this._vertexDeclaration = null;
        }
    }

    class WebGLGlobalPipeLineCacheInfo {
        constructor() {
            this.globalDefineChangeFlag = new Laya.Vector2();
            this.globalDefineData = Laya.LayaGL.unitRenderModuleDataFactory.createDefineDatas();
        }
    }
    class OneDrawPassCacheInfo {
        constructor() {
            this.matCacheFlag = new Laya.Vector2(-1, -1);
            this.nodeCacheFlag = new Laya.Vector2(-1, -1);
            this.passDefineCacheFlag = new Laya.Vector2(-1, -1);
            this.shaderInss = [];
        }
    }
    function compareCahceFlag(changeFlag, cacheFlag) {
        let needUpdate = false;
        if (changeFlag.x > cacheFlag.x)
            needUpdate = true;
        else if (changeFlag.x === cacheFlag.x) {
            needUpdate = changeFlag.y > cacheFlag.y;
        }
        return needUpdate;
    }
    function coverCahceFlag(coverFlag, oldFlag) {
        let needUpdate = false;
        if (coverFlag.x > oldFlag.x)
            needUpdate = true;
        else if (coverFlag.x === oldFlag.x) {
            needUpdate = coverFlag.y > oldFlag.y;
        }
        if (needUpdate) {
            coverFlag.cloneTo(oldFlag);
        }
        return;
    }
    class WebGLRenderDeviceFactory {
        constructor() {
            this.globalBlockMap = {};
        }
        createShaderData(ownerResource) {
            return new WebGLShaderData(ownerResource);
        }
        createShaderInstance(shaderProcessInfo, shaderPass) {
            let shaderIns = new WebGLShaderInstance();
            shaderIns._create(shaderProcessInfo, shaderPass);
            if (Laya.Shader3D.debugMode) {
                let defineString = shaderProcessInfo.defineString;
                let is2D = shaderProcessInfo.is2D;
                Laya.ShaderVariantCollection.active.add(shaderPass, defineString, is2D);
            }
            return shaderIns;
        }
        createIndexBuffer(bufferUsageType) {
            return new WebGLIndexBuffer(Laya.BufferTargetType.ELEMENT_ARRAY_BUFFER, bufferUsageType);
        }
        createVertexBuffer(bufferUsageType) {
            return new WebGLVertexBuffer(Laya.BufferTargetType.ARRAY_BUFFER, bufferUsageType);
        }
        createBufferState() {
            return new WebGLBufferState();
        }
        createRenderGeometryElement(mode, drawType) {
            return new WebGLRenderGeometryElement(mode, drawType);
        }
        createGlobalUniformMap(blockName) {
            let comMap = this.globalBlockMap[blockName];
            if (!comMap)
                comMap = this.globalBlockMap[blockName] = new WebGLCommandUniformMap(blockName);
            return comMap;
        }
        createEngine(config, canvas) {
            let engine;
            let glConfig = { stencil: Laya.Config.isStencil, alpha: Laya.Config.isAlpha, antialias: Laya.Config.isAntialias, premultipliedAlpha: Laya.Config.premultipliedAlpha, preserveDrawingBuffer: Laya.Config.preserveDrawingBuffer, depth: Laya.Config.isDepth, failIfMajorPerformanceCaveat: Laya.Config.isfailIfMajorPerformanceCaveat, powerPreference: Laya.Config.powerPreference };
            const webglMode = Laya.Config.useWebGL2 ? exports.WebGLMode.Auto : exports.WebGLMode.WebGL1;
            engine = new WebGLEngine(glConfig, webglMode);
            engine.initRenderEngine(canvas.source);
            var gl = engine._context;
            if (Laya.Config.printWebglOrder)
                this._replaceWebglcall(gl);
            if (gl) {
                new Laya.LayaGL();
            }
            Laya.LayaGL.renderEngine = engine;
            Laya.LayaGL.textureContext = engine.getTextureContext();
            return Promise.resolve();
        }
        _replaceWebglcall(gl) {
            var tempgl = {};
            for (const key in gl) {
                if (typeof gl[key] == "function" && key != "getError" && key != "__SPECTOR_Origin_getError" && key != "__proto__") {
                    tempgl[key] = gl[key];
                    gl[key] = function () {
                        let arr = [];
                        for (let i = 0; i < arguments.length; i++) {
                            arr.push(arguments[i]);
                        }
                        let result = tempgl[key].apply(gl, arr);
                        let err = gl.getError();
                        if (err) {
                            debugger;
                        }
                        return result;
                    };
                }
            }
        }
    }
    Laya.Laya.addBeforeInitCallback(() => {
        if (!Laya.LayaGL.renderDeviceFactory)
            Laya.LayaGL.renderDeviceFactory = new WebGLRenderDeviceFactory();
    });

    exports.BatchManager = BatchManager;
    exports.GL2TextureContext = GL2TextureContext;
    exports.GLBuffer = GLBuffer;
    exports.GLObject = GLObject;
    exports.GLParams = GLParams;
    exports.GLRenderDrawContext = GLRenderDrawContext;
    exports.GLRenderState = GLRenderState;
    exports.GLShaderInstance = GLShaderInstance;
    exports.GLTextureContext = GLTextureContext;
    exports.GLVertexState = GLVertexState;
    exports.GlCapable = GlCapable;
    exports.OneDrawPassCacheInfo = OneDrawPassCacheInfo;
    exports.Pass2DCacheInfo = Pass2DCacheInfo;
    exports.SequenceFrame2DInstanceBatch = SequenceFrame2DInstanceBatch;
    exports.SequenceFrame2DInstanceBatchTool = SequenceFrame2DInstanceBatchTool;
    exports.VertexArrayObject = VertexArrayObject;
    exports.Web2DBaseRenderDataHandle = Web2DBaseRenderDataHandle;
    exports.Web2DGraphic2DIndexCloneDataView = Web2DGraphic2DIndexCloneDataView;
    exports.Web2DGraphic2DIndexDataView = Web2DGraphic2DIndexDataView;
    exports.Web2DGraphic2DVertexDataView = Web2DGraphic2DVertexDataView;
    exports.Web2DGraphicWholeBuffer = Web2DGraphicWholeBuffer;
    exports.Web2DGraphicsBufferDataView = Web2DGraphicsBufferDataView;
    exports.Web2DGraphicsIndexBatchBuffer = Web2DGraphicsIndexBatchBuffer;
    exports.Web2DGraphicsIndexBuffer = Web2DGraphicsIndexBuffer;
    exports.Web2DGraphicsVertexBuffer = Web2DGraphicsVertexBuffer;
    exports.WebDefineDatas = WebDefineDatas;
    exports.WebEmptyRender2DDataHandle = WebEmptyRender2DDataHandle;
    exports.WebGLBlit2DQuadCMD = WebGLBlit2DQuadCMD;
    exports.WebGLBufferState = WebGLBufferState;
    exports.WebGLCommandUniformMap = WebGLCommandUniformMap;
    exports.WebGLConfig = WebGLConfig;
    exports.WebGLDraw2DElementCMD = WebGLDraw2DElementCMD;
    exports.WebGLEngine = WebGLEngine;
    exports.WebGLGlobalPipeLineCacheInfo = WebGLGlobalPipeLineCacheInfo;
    exports.WebGLIndexBuffer = WebGLIndexBuffer;
    exports.WebGLInternalRT = WebGLInternalRT;
    exports.WebGLInternalTex = WebGLInternalTex;
    exports.WebGLPrimitiveRenderElement2D = WebGLPrimitiveRenderElement2D;
    exports.WebGLRender2DProcess = WebGLRender2DProcess;
    exports.WebGLRenderDeviceFactory = WebGLRenderDeviceFactory;
    exports.WebGLRenderElement2D = WebGLRenderElement2D;
    exports.WebGLRenderGeometryElement = WebGLRenderGeometryElement;
    exports.WebGLSetRenderData = WebGLSetRenderData;
    exports.WebGLSetRendertarget2DCMD = WebGLSetRendertarget2DCMD;
    exports.WebGLSetShaderDefine = WebGLSetShaderDefine;
    exports.WebGLShaderData = WebGLShaderData;
    exports.WebGLShaderInstance = WebGLShaderInstance;
    exports.WebGLSubUniformBuffer = WebGLSubUniformBuffer;
    exports.WebGLUniformBuffer = WebGLUniformBuffer;
    exports.WebGLUniformBufferBase = WebGLUniformBufferBase;
    exports.WebGLUniformBufferDescriptor = WebGLUniformBufferDescriptor;
    exports.WebGLUniformBufferManager = WebGLUniformBufferManager;
    exports.WebGLVertexBuffer = WebGLVertexBuffer;
    exports.WebGlobalRenderData = WebGlobalRenderData;
    exports.WebGraphics2DBufferBlock = WebGraphics2DBufferBlock;
    exports.WebGraphics2DVertexBlock = WebGraphics2DVertexBlock;
    exports.WebGraphicsBatch = WebGraphicsBatch;
    exports.WebMesh2DRenderDataHandle = WebMesh2DRenderDataHandle;
    exports.WebPrimitiveDataHandle = WebPrimitiveDataHandle;
    exports.WebRender2DDataHandle = WebRender2DDataHandle;
    exports.WebRender2DPass = WebRender2DPass;
    exports.WebRender2DPassManager = WebRender2DPassManager;
    exports.WebRenderStruct2D = WebRenderStruct2D;
    exports.WebShaderPass = WebShaderPass;
    exports.WebSpineRenderDataHandle = WebSpineRenderDataHandle;
    exports.WebSubShader = WebSubShader;
    exports.WebUnitRenderModuleDataFactory = WebUnitRenderModuleDataFactory;
    exports.WebglRenderContext2D = WebglRenderContext2D;
    exports.compareCahceFlag = compareCahceFlag;
    exports.coverCahceFlag = coverCahceFlag;

})(window.Laya = window.Laya || {}, Laya);
//# sourceMappingURL=laya.webgl_2D.js.map
