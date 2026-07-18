#if UNITY_EDITOR
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEditor;
using UnityEngine;

public class MaterialFitUnityMultiViewCapture : EditorWindow
{
    private GameObject targetObject;
    private Camera captureCamera;
    private string outputFolderPath = "";
    private string filePrefix = "unity_ref";
    private string yawDegrees = "0,45,90,135,180,225,270,315";
    private string pitchDegrees = "0";
    private int imageWidth = 900;
    private int imageHeight = 700;
    private float distanceScale = 2.2f;
    private float minDistance = 1.0f;
    private float fieldOfView = 35.0f;
    private Color backgroundColor = Color.clear;
    private bool transparentBackground = true;
    private bool useSilhouetteMaskAlpha = true;
    private bool keyBackgroundToAlpha = false;
    private bool exportMask = false;
    private float backgroundKeyTolerance = 0.02f;
    private float backgroundKeySoftness = 0.06f;
    private bool useCameraProjection = false;
    private bool useOrthographic = true;
    private float orthographicScale = 4.0f;

    [MenuItem("Material Fit/Multi-view Capture Window", false, 20)]
    public static void ShowWindow()
    {
        GetWindow<MaterialFitUnityMultiViewCapture>("Material Fit Capture");
    }

    private void OnEnable()
    {
        if (targetObject == null)
        {
            targetObject = Selection.activeGameObject;
        }
        if (captureCamera == null)
        {
            captureCamera = Camera.main;
        }
    }

    private void OnGUI()
    {
        EditorGUILayout.LabelField("参考图导出", EditorStyles.boldLabel);
        targetObject = (GameObject)EditorGUILayout.ObjectField("目标模型根节点", targetObject, typeof(GameObject), true);
        captureCamera = (Camera)EditorGUILayout.ObjectField("截图相机", captureCamera, typeof(Camera), true);

        EditorGUILayout.LabelField("导出目录");
        using (new EditorGUILayout.HorizontalScope())
        {
            outputFolderPath = EditorGUILayout.TextField(outputFolderPath);
            if (GUILayout.Button("浏览...", GUILayout.Width(72)))
            {
                string initialPath = ResolveInitialOutputPath(outputFolderPath);
                string selectedPath = EditorUtility.OpenFolderPanel("选择 Unity 参考图导出目录", initialPath, "");
                if (!string.IsNullOrEmpty(selectedPath))
                {
                    outputFolderPath = selectedPath;
                    GUI.FocusControl(null);
                }
            }
        }
        EditorGUILayout.HelpBox("导出目录可以是电脑上的任意文件夹，不再限制在当前 Unity 项目的 Assets 目录内。建议直接选择 Material Fit 项目的 inputs/unity_references 目录，或先导出到临时目录后在工具界面导入。", MessageType.Info);
        filePrefix = EditorGUILayout.TextField("文件名前缀", filePrefix);

        EditorGUILayout.Space();
        EditorGUILayout.LabelField("视角", EditorStyles.boldLabel);
        yawDegrees = EditorGUILayout.TextField("水平角列表", yawDegrees);
        pitchDegrees = EditorGUILayout.TextField("俯仰角列表", pitchDegrees);
        distanceScale = EditorGUILayout.FloatField("距离倍率", distanceScale);
        minDistance = EditorGUILayout.FloatField("最小距离", minDistance);
        EditorGUILayout.HelpBox("不同引擎中相同 distance scale / FOV 不一定表现一致。Unity/Laya 工具默认统一使用 900x700、正交相机、旋转目标；metadata 只用于备查，不作为 Laya 设置来源。", MessageType.None);

        EditorGUILayout.Space();
        EditorGUILayout.LabelField("渲染", EditorStyles.boldLabel);
        imageWidth = EditorGUILayout.IntField("宽度", imageWidth);
        imageHeight = EditorGUILayout.IntField("高度", imageHeight);
        useCameraProjection = EditorGUILayout.Toggle("使用当前相机投影", useCameraProjection);
        if (useCameraProjection && captureCamera != null)
        {
            using (new EditorGUI.DisabledScope(true))
            {
                EditorGUILayout.Toggle("相机为正交", captureCamera.orthographic);
                if (captureCamera.orthographic)
                {
                    EditorGUILayout.FloatField("相机正交尺寸", captureCamera.orthographicSize);
                }
                else
                {
                    EditorGUILayout.FloatField("相机视野角 FOV", captureCamera.fieldOfView);
                }
            }
        }
        else
        {
            useOrthographic = EditorGUILayout.Toggle("使用正交相机", useOrthographic);
            if (useOrthographic)
            {
                orthographicScale = EditorGUILayout.FloatField("正交垂直尺寸", orthographicScale);
            }
            else
            {
                fieldOfView = EditorGUILayout.FloatField("视野角 FOV", fieldOfView);
            }
        }
        transparentBackground = EditorGUILayout.Toggle("透明背景", transparentBackground);
        backgroundColor = EditorGUILayout.ColorField("背景颜色", backgroundColor);
        useSilhouetteMaskAlpha = EditorGUILayout.Toggle("用轮廓遮罩生成 Alpha", useSilhouetteMaskAlpha);
        keyBackgroundToAlpha = EditorGUILayout.Toggle("按背景色扣 Alpha", keyBackgroundToAlpha);
        using (new EditorGUI.DisabledScope(!keyBackgroundToAlpha || useSilhouetteMaskAlpha))
        {
            backgroundKeyTolerance = EditorGUILayout.Slider("扣色容差", backgroundKeyTolerance, 0.0f, 0.25f);
            backgroundKeySoftness = EditorGUILayout.Slider("扣色柔和度", backgroundKeySoftness, 0.0f, 0.25f);
        }
        exportMask = EditorGUILayout.Toggle("导出 Alpha 遮罩", exportMask);
        EditorGUILayout.HelpBox("Laya 端已支持按 Unity 参考图尺寸自动设置截图 width/height。只要这里导出的参考图尺寸固定，Laya 后续评分会优先使用相同画布尺寸。", MessageType.Info);

        EditorGUILayout.Space();
        using (new EditorGUI.DisabledScope(targetObject == null || imageWidth <= 0 || imageHeight <= 0))
        {
            if (GUILayout.Button("导出多视角参考图"))
            {
                Capture();
            }
        }

        EditorGUILayout.HelpBox(
            "把脚本放在 Unity 项目的 Editor 目录下。选择鱼/模型根节点、截图相机和导出目录后，会按每个 yaw/pitch 组合导出 PNG，并生成 metadata JSON。",
            MessageType.Info);
    }

    private void Capture()
    {
        List<float> yaws = ParseFloatList(yawDegrees);
        List<float> pitches = ParseFloatList(pitchDegrees);
        if (yaws.Count == 0 || pitches.Count == 0)
        {
            EditorUtility.DisplayDialog("Material Fit", "水平角列表和俯仰角列表至少要各包含一个数字。", "确定");
            return;
        }

        Bounds bounds;
        if (!TryGetRenderBounds(targetObject, out bounds))
        {
            EditorUtility.DisplayDialog("Material Fit", "目标模型下没有可渲染 Renderer，无法计算包围盒。", "确定");
            return;
        }

        string absoluteOutputPath = ResolveOutputPath(outputFolderPath);
        if (string.IsNullOrEmpty(absoluteOutputPath))
        {
            EditorUtility.DisplayDialog("Material Fit", "请先选择或输入导出目录。", "确定");
            return;
        }
        Directory.CreateDirectory(absoluteOutputPath);

        Camera camera = captureCamera;
        GameObject temporaryCameraObject = null;
        if (camera == null)
        {
            temporaryCameraObject = new GameObject("MaterialFit_TemporaryCaptureCamera");
            temporaryCameraObject.hideFlags = HideFlags.HideAndDontSave;
            camera = temporaryCameraObject.AddComponent<Camera>();
        }

        CameraState originalState = CameraState.FromCamera(camera);
        TransformState originalTargetState = TransformState.FromTransform(targetObject.transform);
        bool rotateTargetInsteadOfCamera = targetObject != null && camera != null && IsDescendantOf(targetObject.transform, camera.transform);
        bool effectiveUseOrthographic = useCameraProjection && captureCamera != null ? camera.orthographic : useOrthographic;
        float effectiveFieldOfView = useCameraProjection && captureCamera != null ? camera.fieldOfView : fieldOfView;
        float effectiveOrthographicSize = useCameraProjection && captureCamera != null
            ? camera.orthographicSize
            : Mathf.Max(0.01f, orthographicScale);
        ModelGeometryMetadata modelGeometry = BuildModelGeometryMetadata(targetObject);
        CaptureMetadata metadata = new CaptureMetadata
        {
            exporterVersion = "1.1.0",
            exportedAtUtc = System.DateTime.UtcNow.ToString("o"),
            unityVersion = Application.unityVersion,
            targetName = targetObject.name,
            targetAssetPath = GetTargetAssetPath(targetObject),
            outputFolder = absoluteOutputPath,
            imageWidth = imageWidth,
            imageHeight = imageHeight,
            distanceScale = distanceScale,
            minDistance = minDistance,
            transparentBackground = transparentBackground,
            useSilhouetteMaskAlpha = useSilhouetteMaskAlpha,
            keyBackgroundToAlpha = keyBackgroundToAlpha,
            exportMask = exportMask,
            backgroundKeyTolerance = backgroundKeyTolerance,
            backgroundKeySoftness = backgroundKeySoftness,
            useCameraProjection = useCameraProjection,
            captureMode = rotateTargetInsteadOfCamera ? "rotate_target" : "orbit_camera",
            useOrthographic = effectiveUseOrthographic,
            fieldOfView = effectiveFieldOfView,
            orthographicScale = orthographicScale,
            orthographicSize = effectiveOrthographicSize,
            targetCenter = ToArray(bounds.center),
            targetSize = ToArray(bounds.size),
            modelGeometry = modelGeometry
        };

        try
        {
            int viewIndex = 0;
            foreach (float pitch in pitches)
            {
                int pitchBaseIndex = viewIndex;
                foreach (float yaw in yaws)
                {
                    float outputYaw = MirrorYawForLayaName(yaw);
                    int outputViewIndex = ResolveOutputViewIndex(yaws, outputYaw, pitchBaseIndex, viewIndex);
                    string fileName = string.Format(CultureInfo.InvariantCulture, "{0}_v{1:000}_yaw{2}_pitch{3}.png", filePrefix, outputViewIndex, FormatAngle(outputYaw), FormatAngle(pitch));
                    string maskFileName = string.Format(CultureInfo.InvariantCulture, "{0}_v{1:000}_yaw{2}_pitch{3}_mask.png", filePrefix, outputViewIndex, FormatAngle(outputYaw), FormatAngle(pitch));
                    string imagePath = Path.Combine(absoluteOutputPath, fileName);
                    string maskPath = exportMask ? Path.Combine(absoluteOutputPath, maskFileName) : string.Empty;
                    if (rotateTargetInsteadOfCamera)
                    {
                        ConfigureFixedCameraForCapture(camera, bounds, effectiveUseOrthographic, effectiveFieldOfView, effectiveOrthographicSize);
                        RotateTargetForView(targetObject.transform, originalTargetState.localRotation, yaw, pitch);
                    }
                    else
                    {
                        ConfigureCameraForView(camera, bounds, yaw, pitch, effectiveUseOrthographic, effectiveFieldOfView, effectiveOrthographicSize);
                    }
                    RenderCameraToPng(camera, targetObject, imagePath, maskPath, imageWidth, imageHeight, backgroundColor, useSilhouetteMaskAlpha, keyBackgroundToAlpha, backgroundKeyTolerance, backgroundKeySoftness);
                    metadata.views.Add(new CaptureView
                    {
                        index = outputViewIndex,
                        yaw = outputYaw,
                        captureYaw = yaw,
                        pitch = pitch,
                        imagePath = imagePath,
                        fileName = fileName,
                        maskPath = maskPath,
                        maskFileName = exportMask ? maskFileName : string.Empty,
                        cameraPosition = ToArray(camera.transform.position),
                        cameraRotationEuler = ToArray(camera.transform.rotation.eulerAngles),
                        targetLocalRotationEuler = ToArray(targetObject.transform.localRotation.eulerAngles)
                    });
                    viewIndex++;
                }
            }

            metadata.views.Sort((left, right) => left.index.CompareTo(right.index));
            string metadataPath = Path.Combine(absoluteOutputPath, filePrefix + "_multiview_metadata.json");
            File.WriteAllText(metadataPath, UnityEngine.JsonUtility.ToJson(metadata, true));
            AssetDatabase.Refresh();
            Debug.Log("Material Fit multi-view capture exported: " + absoluteOutputPath);
            EditorUtility.DisplayDialog("Material Fit", "多视角参考图导出完成：\n" + absoluteOutputPath, "确定");
        }
        finally
        {
            originalTargetState.ApplyTo(targetObject.transform);
            originalState.ApplyTo(camera);
            if (temporaryCameraObject != null)
            {
                DestroyImmediate(temporaryCameraObject);
            }
        }
    }

    private void ConfigureCameraForView(Camera camera, Bounds bounds, float yaw, float pitch, bool effectiveUseOrthographic, float effectiveFieldOfView, float effectiveOrthographicSize)
    {
        Vector3 center = bounds.center;
        float radius = bounds.extents.magnitude;
        float distance = Mathf.Max(minDistance, radius * distanceScale);
        Quaternion viewRotation = Quaternion.Euler(pitch, yaw, 0.0f);
        Vector3 forward = viewRotation * Vector3.forward;

        camera.transform.position = center - forward * distance;
        camera.transform.rotation = Quaternion.LookRotation(forward, Vector3.up);
        camera.nearClipPlane = Mathf.Max(0.01f, distance - radius * 3.0f);
        camera.farClipPlane = distance + radius * 4.0f;
        ApplyProjectionAndClear(camera, effectiveUseOrthographic, effectiveFieldOfView, effectiveOrthographicSize);
    }

    private void ConfigureFixedCameraForCapture(Camera camera, Bounds bounds, bool effectiveUseOrthographic, float effectiveFieldOfView, float effectiveOrthographicSize)
    {
        float radius = bounds.extents.magnitude;
        camera.nearClipPlane = 0.01f;
        camera.farClipPlane = Mathf.Max(camera.farClipPlane, radius * 10.0f + 100.0f);
        ApplyProjectionAndClear(camera, effectiveUseOrthographic, effectiveFieldOfView, effectiveOrthographicSize);
    }

    private void ApplyProjectionAndClear(Camera camera, bool effectiveUseOrthographic, float effectiveFieldOfView, float effectiveOrthographicSize)
    {
        camera.clearFlags = transparentBackground ? CameraClearFlags.SolidColor : CameraClearFlags.Skybox;
        camera.backgroundColor = backgroundColor;
        camera.orthographic = effectiveUseOrthographic;
        if (effectiveUseOrthographic)
        {
            camera.orthographicSize = Mathf.Max(0.01f, effectiveOrthographicSize);
        }
        else
        {
            camera.fieldOfView = effectiveFieldOfView;
        }
    }

    private static void RotateTargetForView(Transform target, Quaternion baseLocalRotation, float yaw, float pitch)
    {
        target.localRotation = baseLocalRotation * Quaternion.Euler(-pitch, -yaw, 0.0f);
    }

    private static void RenderCameraToPng(Camera camera, GameObject targetObject, string imagePath, string maskPath, int width, int height, Color keyColor, bool useSilhouetteMask, bool keyBackground, float keyTolerance, float keySoftness)
    {
        RenderTexture renderTexture = new RenderTexture(Mathf.Max(1, width), Mathf.Max(1, height), 24, RenderTextureFormat.ARGB32);
        renderTexture.antiAliasing = 8;
        RenderTexture previousActive = RenderTexture.active;
        RenderTexture previousTarget = camera.targetTexture;

        Texture2D texture = null;
        Texture2D maskTexture = null;
        try
        {
            camera.targetTexture = renderTexture;
            RenderTexture.active = renderTexture;
            camera.Render();

            texture = new Texture2D(renderTexture.width, renderTexture.height, TextureFormat.RGBA32, false);
            texture.ReadPixels(new Rect(0, 0, renderTexture.width, renderTexture.height), 0, 0);
            texture.Apply();

            if (useSilhouetteMask)
            {
                maskTexture = RenderSilhouetteMask(camera, targetObject, width, height);
                if (maskTexture != null)
                {
                    ApplyAlphaMask(texture, maskTexture);
                }
            }
            else if (keyBackground)
            {
                ApplyBackgroundAlphaKey(texture, keyColor, keyTolerance, keySoftness);
            }

            if (!string.IsNullOrEmpty(maskPath))
            {
                if (maskTexture != null)
                {
                    File.WriteAllBytes(maskPath, maskTexture.EncodeToPNG());
                }
                else
                {
                    WriteAlphaMaskPng(texture, maskPath);
                }
            }

            byte[] bytes = texture.EncodeToPNG();
            File.WriteAllBytes(imagePath, bytes);
        }
        finally
        {
            if (texture != null)
            {
                DestroyImmediate(texture);
            }
            if (maskTexture != null)
            {
                DestroyImmediate(maskTexture);
            }
            camera.targetTexture = previousTarget;
            RenderTexture.active = previousActive;
            renderTexture.Release();
            DestroyImmediate(renderTexture);
        }
    }

    private static Texture2D RenderSilhouetteMask(Camera camera, GameObject targetObject, int width, int height)
    {
        RenderTexture maskRenderTexture = new RenderTexture(Mathf.Max(1, width), Mathf.Max(1, height), 24, RenderTextureFormat.ARGB32);
        maskRenderTexture.antiAliasing = 8;
        RenderTexture previousActive = RenderTexture.active;
        RenderTexture previousTarget = camera.targetTexture;
        CameraClearFlags previousClearFlags = camera.clearFlags;
        Color previousBackground = camera.backgroundColor;

        Renderer[] targetRenderers = targetObject.GetComponentsInChildren<Renderer>(true);
        Renderer[] sceneRenderers = Object.FindObjectsOfType<Renderer>();
        List<RendererState> rendererStates = new List<RendererState>();
        Material maskMaterial = CreateMaskMaterial();
        if (maskMaterial == null)
        {
            return null;
        }

        try
        {
            HashSet<Renderer> targetSet = new HashSet<Renderer>(targetRenderers);
            for (int i = 0; i < sceneRenderers.Length; i++)
            {
                Renderer renderer = sceneRenderers[i];
                RendererState state = RendererState.FromRenderer(renderer);
                rendererStates.Add(state);
                if (targetSet.Contains(renderer))
                {
                    Material[] maskMaterials = new Material[renderer.sharedMaterials.Length];
                    for (int j = 0; j < maskMaterials.Length; j++)
                    {
                        maskMaterials[j] = maskMaterial;
                    }
                    renderer.sharedMaterials = maskMaterials;
                    renderer.enabled = true;
                }
                else
                {
                    renderer.enabled = false;
                }
            }

            camera.targetTexture = maskRenderTexture;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = Color.black;
            RenderTexture.active = maskRenderTexture;
            camera.Render();

            Texture2D mask = new Texture2D(maskRenderTexture.width, maskRenderTexture.height, TextureFormat.RGBA32, false);
            mask.ReadPixels(new Rect(0, 0, maskRenderTexture.width, maskRenderTexture.height), 0, 0);
            mask.Apply();
            NormalizeMaskTexture(mask);
            return mask;
        }
        finally
        {
            for (int i = 0; i < rendererStates.Count; i++)
            {
                rendererStates[i].Apply();
            }
            if (maskMaterial != null)
            {
                DestroyImmediate(maskMaterial);
            }
            camera.targetTexture = previousTarget;
            camera.clearFlags = previousClearFlags;
            camera.backgroundColor = previousBackground;
            RenderTexture.active = previousActive;
            maskRenderTexture.Release();
            DestroyImmediate(maskRenderTexture);
        }
    }

    private static Material CreateMaskMaterial()
    {
        Shader shader = Shader.Find("Unlit/Color");
        if (shader == null)
        {
            shader = Shader.Find("Hidden/Internal-Colored");
        }
        if (shader == null)
        {
            Debug.LogWarning("Material Fit could not find a mask shader. Falling back to the color buffer alpha.");
            return null;
        }
        Material material = new Material(shader);
        material.hideFlags = HideFlags.HideAndDontSave;
        if (material.HasProperty("_Color"))
        {
            material.SetColor("_Color", Color.white);
        }
        return material;
    }

    private static void NormalizeMaskTexture(Texture2D mask)
    {
        Color[] pixels = mask.GetPixels();
        for (int i = 0; i < pixels.Length; i++)
        {
            float value = Mathf.Clamp01((pixels[i].r + pixels[i].g + pixels[i].b) / 3.0f);
            pixels[i] = new Color(value, value, value, 1.0f);
        }
        mask.SetPixels(pixels);
        mask.Apply();
    }

    private static void ApplyAlphaMask(Texture2D texture, Texture2D mask)
    {
        Color[] pixels = texture.GetPixels();
        Color[] maskPixels = mask.GetPixels();
        int count = Mathf.Min(pixels.Length, maskPixels.Length);
        for (int i = 0; i < count; i++)
        {
            float alpha = Mathf.Clamp01((maskPixels[i].r + maskPixels[i].g + maskPixels[i].b) / 3.0f);
            Color pixel = pixels[i];
            pixel.a = alpha;
            pixels[i] = pixel;
        }
        texture.SetPixels(pixels);
        texture.Apply();
    }

    private static void ApplyBackgroundAlphaKey(Texture2D texture, Color keyColor, float tolerance, float softness)
    {
        Color[] pixels = texture.GetPixels();
        float safeSoftness = Mathf.Max(0.0001f, softness);
        for (int i = 0; i < pixels.Length; i++)
        {
            Color pixel = pixels[i];
            float distance = ColorDistanceRgb(pixel, keyColor);
            float alphaScale = Mathf.Clamp01((distance - tolerance) / safeSoftness);
            pixel.a *= alphaScale;
            pixels[i] = pixel;
        }
        texture.SetPixels(pixels);
        texture.Apply();
    }

    private static void WriteAlphaMaskPng(Texture2D source, string maskPath)
    {
        Color[] sourcePixels = source.GetPixels();
        Color[] maskPixels = new Color[sourcePixels.Length];
        for (int i = 0; i < sourcePixels.Length; i++)
        {
            float alpha = sourcePixels[i].a;
            maskPixels[i] = new Color(alpha, alpha, alpha, 1.0f);
        }

        Texture2D mask = new Texture2D(source.width, source.height, TextureFormat.RGBA32, false);
        mask.SetPixels(maskPixels);
        mask.Apply();
        File.WriteAllBytes(maskPath, mask.EncodeToPNG());
        DestroyImmediate(mask);
    }

    private static float ColorDistanceRgb(Color a, Color b)
    {
        float dr = a.r - b.r;
        float dg = a.g - b.g;
        float db = a.b - b.b;
        return Mathf.Sqrt(dr * dr + dg * dg + db * db);
    }

    private static List<float> ParseFloatList(string text)
    {
        List<float> values = new List<float>();
        if (string.IsNullOrEmpty(text))
        {
            return values;
        }

        string[] parts = text.Split(',');
        foreach (string rawPart in parts)
        {
            float value;
            if (float.TryParse(rawPart.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out value))
            {
                values.Add(value);
            }
        }
        return values;
    }

    private static bool TryGetRenderBounds(GameObject gameObject, out Bounds bounds)
    {
        Renderer[] renderers = gameObject.GetComponentsInChildren<Renderer>();
        if (renderers.Length == 0)
        {
            bounds = new Bounds(gameObject.transform.position, Vector3.one);
            return false;
        }

        bounds = renderers[0].bounds;
        for (int i = 1; i < renderers.Length; i++)
        {
            bounds.Encapsulate(renderers[i].bounds);
        }
        return true;
    }

    private static ModelGeometryMetadata BuildModelGeometryMetadata(GameObject target)
    {
        ModelGeometryMetadata metadata = new ModelGeometryMetadata
        {
            targetName = target.name,
            coordinateSystem = "laya_right_handed_x_flipped_from_unity",
            boundsSpace = "target_local_current_pose",
            poseSource = "visible_renderer_vertices",
            targetPivot = new float[] { 0.0f, 0.0f, 0.0f }
        };

        Matrix4x4 worldToTarget = target.transform.worldToLocalMatrix;
        Renderer[] renderers = target.GetComponentsInChildren<Renderer>(true);
        List<Transform> uniqueBones = new List<Transform>();
        bool hasBounds = false;
        Vector3 min = Vector3.zero;
        Vector3 max = Vector3.zero;

        foreach (Renderer renderer in renderers)
        {
            if (renderer == null)
            {
                continue;
            }

            Mesh sourceMesh = null;
            Mesh vertexMesh = null;
            Mesh bakedMesh = null;
            SkinnedMeshRenderer skinned = renderer as SkinnedMeshRenderer;
            if (skinned != null)
            {
                sourceMesh = skinned.sharedMesh;
                if (sourceMesh != null)
                {
                    bakedMesh = new Mesh();
                    bakedMesh.name = sourceMesh.name + "_MaterialFitBaked";
                    skinned.BakeMesh(bakedMesh);
                    vertexMesh = bakedMesh;
                }
                foreach (Transform bone in skinned.bones)
                {
                    if (bone != null && !uniqueBones.Contains(bone))
                    {
                        uniqueBones.Add(bone);
                    }
                }
            }
            else
            {
                MeshFilter filter = renderer.GetComponent<MeshFilter>();
                sourceMesh = filter != null ? filter.sharedMesh : null;
                vertexMesh = sourceMesh;
            }

            bool visible = renderer.enabled && renderer.gameObject.activeInHierarchy;
            bool vertexReadable = vertexMesh != null && (bakedMesh != null || vertexMesh.isReadable);
            bool included = visible && vertexMesh != null;
            RendererGeometryMetadata rendererMetadata = BuildRendererGeometryMetadata(
                renderer,
                sourceMesh,
                included,
                vertexReadable ? "current_pose_vertices" : (included ? "renderer_bounds_fallback" : "excluded"),
                target.transform
            );
            metadata.renderers.Add(rendererMetadata);
            metadata.rendererCount++;
            metadata.materialSlotCount += rendererMetadata.materialSlotCount;
            metadata.totalVertexCount += rendererMetadata.vertexCount;
            metadata.totalTriangleCount += rendererMetadata.triangleCount;
            metadata.totalSubMeshCount += rendererMetadata.subMeshCount;
            if (included && vertexReadable)
            {
                metadata.visibleRendererCount++;
                metadata.exactBoundsRendererCount++;
                Matrix4x4 localToTarget = worldToTarget * renderer.transform.localToWorldMatrix;
                Vector3[] vertices = vertexMesh.vertices;
                foreach (Vector3 vertex in vertices)
                {
                    Vector3 point = ToLayaPosition(localToTarget.MultiplyPoint3x4(vertex));
                    if (!hasBounds)
                    {
                        min = point;
                        max = point;
                        hasBounds = true;
                    }
                    else
                    {
                        min = Vector3.Min(min, point);
                        max = Vector3.Max(max, point);
                    }
                }
            }
            else if (included)
            {
                metadata.visibleRendererCount++;
                metadata.fallbackBoundsRendererCount++;
                Bounds rendererBounds = renderer.bounds;
                for (int cornerIndex = 0; cornerIndex < 8; cornerIndex++)
                {
                    Vector3 worldPoint = new Vector3(
                        (cornerIndex & 1) == 0 ? rendererBounds.min.x : rendererBounds.max.x,
                        (cornerIndex & 2) == 0 ? rendererBounds.min.y : rendererBounds.max.y,
                        (cornerIndex & 4) == 0 ? rendererBounds.min.z : rendererBounds.max.z
                    );
                    Vector3 point = ToLayaPosition(worldToTarget.MultiplyPoint3x4(worldPoint));
                    if (!hasBounds)
                    {
                        min = point;
                        max = point;
                        hasBounds = true;
                    }
                    else
                    {
                        min = Vector3.Min(min, point);
                        max = Vector3.Max(max, point);
                    }
                }
            }

            if (bakedMesh != null)
            {
                Object.DestroyImmediate(bakedMesh);
            }
        }

        metadata.boneCount = uniqueBones.Count;
        foreach (Transform bone in uniqueBones)
        {
            metadata.bones.Add(BuildBoneMetadata(bone, target.transform));
        }

        metadata.actualBounds.valid = hasBounds;
        if (hasBounds)
        {
            Vector3 center = (min + max) * 0.5f;
            Vector3 size = max - min;
            metadata.actualBounds.min = ToArray(min);
            metadata.actualBounds.max = ToArray(max);
            metadata.actualBounds.center = ToArray(center);
            metadata.actualBounds.size = ToArray(size);
            metadata.pivotToBoundsCenter = ToArray(center);
        }
        return metadata;
    }

    private static RendererGeometryMetadata BuildRendererGeometryMetadata(
        Renderer renderer,
        Mesh mesh,
        bool included,
        string boundsSource,
        Transform target
    )
    {
        RendererGeometryMetadata metadata = new RendererGeometryMetadata
        {
            path = GetRelativePath(renderer.transform, target),
            rendererType = renderer.GetType().Name,
            enabled = renderer.enabled,
            activeInHierarchy = renderer.gameObject.activeInHierarchy,
            includedInActualBounds = included,
            boundsSource = boundsSource,
            meshName = mesh != null ? mesh.name : string.Empty,
            meshAssetPath = mesh != null ? AssetDatabase.GetAssetPath(mesh) : string.Empty,
            materialSlotCount = renderer.sharedMaterials != null ? renderer.sharedMaterials.Length : 0
        };
        if (mesh == null)
        {
            return metadata;
        }
        metadata.vertexCount = mesh.vertexCount;
        metadata.subMeshCount = mesh.subMeshCount;
        long indexCount = 0;
        for (int index = 0; index < mesh.subMeshCount; index++)
        {
            indexCount += (long)mesh.GetIndexCount(index);
        }
        metadata.triangleCount = indexCount / 3L;
        return metadata;
    }

    private static BoneGeometryMetadata BuildBoneMetadata(Transform bone, Transform target)
    {
        Vector3 position = ToLayaPosition(bone.localPosition);
        Quaternion rotation = bone.localRotation;
        rotation.x *= -1.0f;
        rotation.w *= -1.0f;
        return new BoneGeometryMetadata
        {
            path = GetRelativePath(bone, target),
            parentPath = bone.parent != null ? GetRelativePath(bone.parent, target) : string.Empty,
            localPosition = ToArray(position),
            localRotation = ToArray(rotation),
            localScale = ToArray(bone.localScale)
        };
    }

    private static string GetRelativePath(Transform node, Transform root)
    {
        if (node == null)
        {
            return string.Empty;
        }
        List<string> parts = new List<string>();
        Transform current = node;
        while (current != null && current != root)
        {
            parts.Add(current.name);
            current = current.parent;
        }
        if (current == root)
        {
            parts.Add(root.name);
        }
        parts.Reverse();
        return string.Join("/", parts.ToArray());
    }

    private static Vector3 ToLayaPosition(Vector3 value)
    {
        return new Vector3(-value.x, value.y, value.z);
    }

    private static bool IsDescendantOf(Transform child, Transform ancestor)
    {
        Transform current = child != null ? child.parent : null;
        while (current != null)
        {
            if (current == ancestor)
            {
                return true;
            }
            current = current.parent;
        }
        return false;
    }

    private static string ResolveOutputPath(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return string.Empty;
        }
        if (Path.IsPathRooted(path))
        {
            return path;
        }
        return Path.GetFullPath(Path.Combine(Directory.GetParent(Application.dataPath).FullName, path));
    }

    private static string ResolveInitialOutputPath(string currentPath)
    {
        string resolved = ResolveOutputPath(currentPath);
        if (!string.IsNullOrEmpty(resolved))
        {
            if (Directory.Exists(resolved))
            {
                return resolved;
            }
            string parent = Path.GetDirectoryName(resolved);
            if (!string.IsNullOrEmpty(parent) && Directory.Exists(parent))
            {
                return parent;
            }
        }
        return Directory.GetParent(Application.dataPath).FullName;
    }

    private static string GetTargetAssetPath(GameObject gameObject)
    {
        Object prefab = PrefabUtility.GetCorrespondingObjectFromSource(gameObject);
        if (prefab != null)
        {
            return AssetDatabase.GetAssetPath(prefab);
        }
        return AssetDatabase.GetAssetPath(gameObject);
    }

    private static string FormatAngle(float angle)
    {
        return angle.ToString("0.###", CultureInfo.InvariantCulture).Replace("-", "m").Replace(".", "p");
    }

    private static float MirrorYawForLayaName(float yaw)
    {
        float mirrored = 360.0f - Mathf.Repeat(yaw, 360.0f);
        if (Mathf.Approximately(mirrored, 360.0f))
        {
            return 0.0f;
        }
        return mirrored;
    }

    private static int ResolveOutputViewIndex(List<float> yaws, float outputYaw, int pitchBaseIndex, int fallbackIndex)
    {
        float normalizedOutputYaw = Mathf.Repeat(outputYaw, 360.0f);
        for (int index = 0; index < yaws.Count; index++)
        {
            if (Mathf.Abs(Mathf.DeltaAngle(yaws[index], normalizedOutputYaw)) < 0.001f)
            {
                return pitchBaseIndex + index;
            }
        }
        return fallbackIndex;
    }

    private static float[] ToArray(Vector3 value)
    {
        return new float[] { value.x, value.y, value.z };
    }

    private static float[] ToArray(Quaternion value)
    {
        return new float[] { value.x, value.y, value.z, value.w };
    }

    [System.Serializable]
    private class CaptureMetadata
    {
        public string exporterVersion = string.Empty;
        public string exportedAtUtc = string.Empty;
        public string unityVersion = string.Empty;
        public string targetName = string.Empty;
        public string targetAssetPath = string.Empty;
        public string outputFolder = string.Empty;
        public int imageWidth = 0;
        public int imageHeight = 0;
        public float distanceScale = 0.0f;
        public float minDistance = 0.0f;
        public bool transparentBackground = true;
        public bool useSilhouetteMaskAlpha = true;
        public bool keyBackgroundToAlpha = false;
        public bool exportMask = false;
        public float backgroundKeyTolerance = 0.0f;
        public float backgroundKeySoftness = 0.0f;
        public bool useCameraProjection = true;
        public string captureMode = string.Empty;
        public bool useOrthographic = false;
        public float fieldOfView = 0.0f;
        public float orthographicScale = 0.0f;
        public float orthographicSize = 0.0f;
        public float[] targetCenter = new float[3];
        public float[] targetSize = new float[3];
        public ModelGeometryMetadata modelGeometry = new ModelGeometryMetadata();
        public List<CaptureView> views = new List<CaptureView>();
    }

    [System.Serializable]
    private class ModelGeometryMetadata
    {
        public string schemaVersion = "material_fit_model_geometry_v1";
        public string targetName = string.Empty;
        public string coordinateSystem = string.Empty;
        public string boundsSpace = string.Empty;
        public string poseSource = string.Empty;
        public float[] targetPivot = new float[3];
        public float[] pivotToBoundsCenter = new float[3];
        public GeometryBoundsMetadata actualBounds = new GeometryBoundsMetadata();
        public int rendererCount = 0;
        public int visibleRendererCount = 0;
        public int exactBoundsRendererCount = 0;
        public int fallbackBoundsRendererCount = 0;
        public int materialSlotCount = 0;
        public int totalVertexCount = 0;
        public long totalTriangleCount = 0;
        public int totalSubMeshCount = 0;
        public int boneCount = 0;
        public List<RendererGeometryMetadata> renderers = new List<RendererGeometryMetadata>();
        public List<BoneGeometryMetadata> bones = new List<BoneGeometryMetadata>();
    }

    [System.Serializable]
    private class GeometryBoundsMetadata
    {
        public bool valid = false;
        public float[] min = new float[3];
        public float[] max = new float[3];
        public float[] center = new float[3];
        public float[] size = new float[3];
    }

    [System.Serializable]
    private class RendererGeometryMetadata
    {
        public string path = string.Empty;
        public string rendererType = string.Empty;
        public bool enabled = false;
        public bool activeInHierarchy = false;
        public bool includedInActualBounds = false;
        public string boundsSource = string.Empty;
        public string meshName = string.Empty;
        public string meshAssetPath = string.Empty;
        public int vertexCount = 0;
        public long triangleCount = 0;
        public int subMeshCount = 0;
        public int materialSlotCount = 0;
    }

    [System.Serializable]
    private class BoneGeometryMetadata
    {
        public string path = string.Empty;
        public string parentPath = string.Empty;
        public float[] localPosition = new float[3];
        public float[] localRotation = new float[4];
        public float[] localScale = new float[3];
    }

    [System.Serializable]
    private class CaptureView
    {
        public int index = 0;
        public float yaw = 0.0f;
        public float captureYaw = 0.0f;
        public float pitch = 0.0f;
        public string imagePath = string.Empty;
        public string fileName = string.Empty;
        public string maskPath = string.Empty;
        public string maskFileName = string.Empty;
        public float[] cameraPosition = new float[3];
        public float[] cameraRotationEuler = new float[3];
        public float[] targetLocalRotationEuler = new float[3];
    }

    private struct CameraState
    {
        public Vector3 position;
        public Quaternion rotation;
        public bool orthographic;
        public float orthographicSize;
        public float fieldOfView;
        public float nearClipPlane;
        public float farClipPlane;
        public CameraClearFlags clearFlags;
        public Color backgroundColor;
        public RenderTexture targetTexture;

        public static CameraState FromCamera(Camera camera)
        {
            return new CameraState
            {
                position = camera.transform.position,
                rotation = camera.transform.rotation,
                orthographic = camera.orthographic,
                orthographicSize = camera.orthographicSize,
                fieldOfView = camera.fieldOfView,
                nearClipPlane = camera.nearClipPlane,
                farClipPlane = camera.farClipPlane,
                clearFlags = camera.clearFlags,
                backgroundColor = camera.backgroundColor,
                targetTexture = camera.targetTexture
            };
        }

        public void ApplyTo(Camera camera)
        {
            camera.transform.position = position;
            camera.transform.rotation = rotation;
            camera.orthographic = orthographic;
            camera.orthographicSize = orthographicSize;
            camera.fieldOfView = fieldOfView;
            camera.nearClipPlane = nearClipPlane;
            camera.farClipPlane = farClipPlane;
            camera.clearFlags = clearFlags;
            camera.backgroundColor = backgroundColor;
            camera.targetTexture = targetTexture;
        }
    }

    private struct TransformState
    {
        public Vector3 localPosition;
        public Quaternion localRotation;
        public Vector3 localScale;

        public static TransformState FromTransform(Transform transform)
        {
            return new TransformState
            {
                localPosition = transform.localPosition,
                localRotation = transform.localRotation,
                localScale = transform.localScale
            };
        }

        public void ApplyTo(Transform transform)
        {
            transform.localPosition = localPosition;
            transform.localRotation = localRotation;
            transform.localScale = localScale;
        }
    }

    private struct RendererState
    {
        public Renderer renderer;
        public bool enabled;
        public Material[] sharedMaterials;

        public static RendererState FromRenderer(Renderer renderer)
        {
            return new RendererState
            {
                renderer = renderer,
                enabled = renderer.enabled,
                sharedMaterials = renderer.sharedMaterials
            };
        }

        public void Apply()
        {
            if (renderer == null)
            {
                return;
            }
            renderer.enabled = enabled;
            renderer.sharedMaterials = sharedMaterials;
        }
    }

}
#endif
