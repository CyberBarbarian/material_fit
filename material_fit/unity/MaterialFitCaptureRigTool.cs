#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

public class MaterialFitCaptureRigTool : EditorWindow
{
    private Camera captureCamera;
    private GameObject modelRoot;
    private Transform capturePivot;
    private Transform modelPose;
    private Vector3 pivotLocalPosition = Vector3.forward * 10.0f;
    private Vector3 modelBaseEuler = Vector3.zero;
    private Vector3 modelFineOffset = Vector3.zero;
    private string pivotMarkerName = "MaterialFitCapturePivot";
    private bool preferPivotMarker = true;
    private string layaPoseJsonPath = "";
    private bool applyPosePositions = false;
    private bool applyPoseScales = false;

    [MenuItem("Material Fit/Capture Rig Tool", false, 30)]
    public static void ShowWindow()
    {
        GetWindow<MaterialFitCaptureRigTool>("Capture Rig");
    }

    private void OnEnable()
    {
        if (captureCamera == null)
        {
            captureCamera = Camera.main;
        }
        if (modelRoot == null && Selection.activeGameObject != null)
        {
            modelRoot = Selection.activeGameObject;
        }
    }

    private void OnGUI()
    {
        EditorGUILayout.LabelField("Capture Pivot Rig", EditorStyles.boldLabel);
        captureCamera = (Camera)EditorGUILayout.ObjectField("Capture Camera", captureCamera, typeof(Camera), true);
        modelRoot = (GameObject)EditorGUILayout.ObjectField("Model Root", modelRoot, typeof(GameObject), true);
        capturePivot = (Transform)EditorGUILayout.ObjectField("Capture Pivot", capturePivot, typeof(Transform), true);
        modelPose = (Transform)EditorGUILayout.ObjectField("Model Pose", modelPose, typeof(Transform), true);
        pivotLocalPosition = EditorGUILayout.Vector3Field("Pivot Local Position", pivotLocalPosition);
        modelBaseEuler = EditorGUILayout.Vector3Field("Model Base Euler", modelBaseEuler);
        pivotMarkerName = EditorGUILayout.TextField("Pivot Marker Name", pivotMarkerName);
        preferPivotMarker = EditorGUILayout.Toggle("Prefer Pivot Marker", preferPivotMarker);
        modelFineOffset = EditorGUILayout.Vector3Field("Model Fine Offset", modelFineOffset);

        using (new EditorGUI.DisabledScope(captureCamera == null || modelRoot == null))
        {
            if (GUILayout.Button("Create / Update Pivot Marker From Render Bounds"))
            {
                CreateOrUpdatePivotMarker();
            }
            if (GUILayout.Button("Create / Recenter Camera -> CapturePivot -> ModelRoot"))
            {
                CreateOrRecenterRig();
            }
        }

        EditorGUILayout.Space();
        EditorGUILayout.LabelField("Laya Pose -> Unity Pose", EditorStyles.boldLabel);
        using (new EditorGUILayout.HorizontalScope())
        {
            layaPoseJsonPath = EditorGUILayout.TextField("Pose JSON", layaPoseJsonPath);
            if (GUILayout.Button("Browse", GUILayout.Width(72)))
            {
                string path = EditorUtility.OpenFilePanel("Select Laya pose JSON", "", "json");
                if (!string.IsNullOrEmpty(path))
                {
                    layaPoseJsonPath = path;
                    GUI.FocusControl(null);
                }
            }
        }
        applyPosePositions = EditorGUILayout.Toggle("Apply Local Positions", applyPosePositions);
        applyPoseScales = EditorGUILayout.Toggle("Apply Local Scales", applyPoseScales);
        using (new EditorGUI.DisabledScope(modelRoot == null || string.IsNullOrEmpty(layaPoseJsonPath)))
        {
            if (GUILayout.Button("Apply Laya Pose To Unity Bones"))
            {
                ApplyLayaPoseToUnity();
            }
        }

        EditorGUILayout.HelpBox(
            "Rig rule: rotate CapturePivot only. ModelRoot fine offset changes the model relative to the pivot and therefore changes the orbit center; keep it fixed after calibration.",
            MessageType.Info);
    }

    private void CreateOrRecenterRig()
    {
        if (captureCamera == null || modelRoot == null)
        {
            return;
        }

        Undo.IncrementCurrentGroup();
        Undo.SetCurrentGroupName("Create Material Fit Capture Rig");

        if (capturePivot == null)
        {
            Transform existing = captureCamera.transform.Find("CapturePivot");
            if (existing != null)
            {
                capturePivot = existing;
            }
            else
            {
                GameObject pivotObject = new GameObject("CapturePivot");
                Undo.RegisterCreatedObjectUndo(pivotObject, "Create CapturePivot");
                capturePivot = pivotObject.transform;
                capturePivot.SetParent(captureCamera.transform, false);
            }
        }
        else if (capturePivot.parent != captureCamera.transform)
        {
            Undo.SetTransformParent(capturePivot, captureCamera.transform, "Parent CapturePivot");
        }

        Undo.RecordObject(capturePivot, "Set CapturePivot Transform");
        capturePivot.localPosition = pivotLocalPosition;
        capturePivot.localRotation = Quaternion.identity;
        capturePivot.localScale = Vector3.one;

        if (modelPose == null)
        {
            Transform existingPose = capturePivot.Find("ModelPose");
            if (existingPose != null)
            {
                modelPose = existingPose;
            }
            else
            {
                GameObject poseObject = new GameObject("ModelPose");
                Undo.RegisterCreatedObjectUndo(poseObject, "Create ModelPose");
                modelPose = poseObject.transform;
                modelPose.SetParent(capturePivot, false);
            }
        }
        else if (modelPose.parent != capturePivot)
        {
            Undo.SetTransformParent(modelPose, capturePivot, "Parent ModelPose");
        }

        Undo.RecordObject(modelPose, "Set ModelPose Transform");
        modelPose.localPosition = Vector3.zero;
        modelPose.localRotation = Quaternion.Euler(modelBaseEuler);
        modelPose.localScale = Vector3.one;

        Undo.SetTransformParent(modelRoot.transform, modelPose, "Parent ModelRoot To ModelPose");

        if (!TryResolvePivotWorldPosition(out Vector3 pivotWorldPosition))
        {
            Debug.LogWarning("Material Fit Capture Rig: could not resolve pivot marker or Renderer bounds.");
            return;
        }

        Vector3 delta = pivotWorldPosition - modelPose.position;
        Undo.RecordObject(modelRoot.transform, "Recenter ModelRoot");
        modelRoot.transform.position -= delta;
        modelRoot.transform.localPosition += modelFineOffset;

        Debug.Log($"Material Fit Capture Rig: recentered '{modelRoot.name}' to pivot '{capturePivot.name}' through '{modelPose.name}'. delta={delta}");
    }

    private void CreateOrUpdatePivotMarker()
    {
        if (modelRoot == null)
        {
            return;
        }
        if (!TryGetRenderBounds(modelRoot, out Bounds bounds))
        {
            Debug.LogWarning("Material Fit Capture Rig: model has no Renderer bounds.");
            return;
        }

        Transform marker = FindDeepChild(modelRoot.transform, pivotMarkerName);
        if (marker == null)
        {
            GameObject markerObject = new GameObject(pivotMarkerName);
            Undo.RegisterCreatedObjectUndo(markerObject, "Create Pivot Marker");
            marker = markerObject.transform;
            marker.SetParent(modelRoot.transform, false);
        }
        Undo.RecordObject(marker, "Update Pivot Marker");
        marker.position = bounds.center;
        marker.localRotation = Quaternion.identity;
        marker.localScale = Vector3.one;
        Selection.activeTransform = marker;
        Debug.Log($"Material Fit Capture Rig: pivot marker '{pivotMarkerName}' set to render bounds center {bounds.center}.");
    }

    private bool TryResolvePivotWorldPosition(out Vector3 pivotWorldPosition)
    {
        if (preferPivotMarker && modelRoot != null && !string.IsNullOrWhiteSpace(pivotMarkerName))
        {
            Transform marker = FindDeepChild(modelRoot.transform, pivotMarkerName);
            if (marker != null)
            {
                pivotWorldPosition = marker.position;
                return true;
            }
        }
        if (modelRoot != null && TryGetRenderBounds(modelRoot, out Bounds bounds))
        {
            pivotWorldPosition = bounds.center;
            return true;
        }
        pivotWorldPosition = Vector3.zero;
        return false;
    }

    private void ApplyLayaPoseToUnity()
    {
        if (modelRoot == null || string.IsNullOrEmpty(layaPoseJsonPath) || !File.Exists(layaPoseJsonPath))
        {
            return;
        }

        string text = File.ReadAllText(layaPoseJsonPath);
        LayaPoseFile pose = JsonUtility.FromJson<LayaPoseFile>(text);
        if (pose == null || pose.bones == null || pose.bones.Length == 0)
        {
            Debug.LogWarning("Material Fit Capture Rig: pose JSON has no bones.");
            return;
        }

        Dictionary<string, Transform> unityBones = new Dictionary<string, Transform>();
        foreach (Transform child in modelRoot.GetComponentsInChildren<Transform>(true))
        {
            if (!unityBones.ContainsKey(child.name))
            {
                unityBones.Add(child.name, child);
            }
        }

        int applied = 0;
        Undo.IncrementCurrentGroup();
        Undo.SetCurrentGroupName("Apply Laya Pose To Unity");
        foreach (LayaBonePose bone in pose.bones)
        {
            if (bone == null || string.IsNullOrEmpty(bone.name))
            {
                continue;
            }
            if (!unityBones.TryGetValue(bone.name, out Transform target))
            {
                continue;
            }

            Undo.RecordObject(target, "Apply Laya Bone Pose");
            if (applyPosePositions && bone.localPosition != null && bone.localPosition.Length >= 3)
            {
                target.localPosition = LayaPositionToUnity(ToVector3(bone.localPosition));
            }
            if (bone.localRotation != null && bone.localRotation.Length >= 4)
            {
                target.localRotation = LayaRotationToUnity(ToQuaternion(bone.localRotation));
            }
            if (applyPoseScales && bone.localScale != null && bone.localScale.Length >= 3)
            {
                target.localScale = ToVector3(bone.localScale);
            }
            applied++;
        }

        Debug.Log($"Material Fit Capture Rig: applied Laya pose to {applied}/{pose.bones.Length} Unity bones.");
    }

    private static Vector3 LayaPositionToUnity(Vector3 layaPosition)
    {
        layaPosition.x *= -1.0f;
        return layaPosition;
    }

    private static Quaternion LayaRotationToUnity(Quaternion layaRotation)
    {
        layaRotation.x *= -1.0f;
        layaRotation.w *= -1.0f;
        layaRotation.Normalize();
        return layaRotation;
    }

    private static Vector3 ToVector3(float[] values)
    {
        return new Vector3(values[0], values[1], values[2]);
    }

    private static Quaternion ToQuaternion(float[] values)
    {
        return new Quaternion(values[0], values[1], values[2], values[3]);
    }

    private static bool TryGetRenderBounds(GameObject root, out Bounds bounds)
    {
        Renderer[] renderers = root.GetComponentsInChildren<Renderer>(true);
        bool hasBounds = false;
        bounds = new Bounds(root.transform.position, Vector3.zero);
        foreach (Renderer renderer in renderers)
        {
            if (renderer == null || !renderer.enabled)
            {
                continue;
            }
            if (!hasBounds)
            {
                bounds = renderer.bounds;
                hasBounds = true;
            }
            else
            {
                bounds.Encapsulate(renderer.bounds);
            }
        }
        return hasBounds;
    }

    private static Transform FindDeepChild(Transform root, string childName)
    {
        if (root == null || string.IsNullOrWhiteSpace(childName))
        {
            return null;
        }
        if (root.name == childName)
        {
            return root;
        }
        foreach (Transform child in root)
        {
            Transform found = FindDeepChild(child, childName);
            if (found != null)
            {
                return found;
            }
        }
        return null;
    }

    [Serializable]
    private class LayaPoseFile
    {
        public LayaBonePose[] bones;
    }

    [Serializable]
    private class LayaBonePose
    {
        public string name;
        public float[] localPosition;
        public float[] localRotation;
        public float[] localScale;
    }

}
#endif
