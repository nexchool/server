/**
 * UploadDocumentModal
 * Modal for uploading a student document.
 * Document type picker, file picker (PDF/images), upload button, loading and error states.
 */
import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TouchableOpacity,
  ActivityIndicator,
  ScrollView,
  Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";
import {
  DOCUMENT_TYPES,
  DOCUMENT_TYPE_LABELS,
  type DocumentTypeValue,
} from "../types";
import type { UseMutationResult } from "@tanstack/react-query";

interface UploadDocumentModalProps {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
  studentId: string;
  uploadMutation: UseMutationResult<
    { id: string } & Record<string, unknown>,
    Error,
    { documentType: DocumentTypeValue; file: { uri: string; name: string } },
    unknown
  >;
}

export function UploadDocumentModal({
  visible,
  onClose,
  onSuccess,
  uploadMutation,
}: UploadDocumentModalProps) {
  const [documentType, setDocumentType] = useState<DocumentTypeValue | "">("");
  const [selectedFile, setSelectedFile] = useState<{
    uri: string;
    name: string;
    mimeType?: string;
  } | null>(null);
  const [showTypePicker, setShowTypePicker] = useState(false);

  const { mutate: upload, isPending, error, reset } = uploadMutation;

  const resetForm = () => {
    setDocumentType("");
    setSelectedFile(null);
    setShowTypePicker(false);
    reset();
  };

  const handleClose = () => {
    resetForm();
    onClose();
  };

  const handlePickFile = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ["image/*", "application/pdf"],
        copyToCacheDirectory: true,
      });

      if (result.canceled) return;

      const asset = result.assets[0];
      if (asset?.uri && asset?.name) {
        setSelectedFile({
          uri: asset.uri,
          name: asset.name,
          mimeType: asset.mimeType ?? undefined,
        });
      }
    } catch (e) {
      console.error("Document picker error:", e);
      Alert.alert("Error", "Failed to pick file");
    }
  };

  const handleUpload = () => {
    if (!documentType || !selectedFile) {
      Alert.alert(
        "Validation",
        documentType ? "Please select a file" : "Please select a document type"
      );
      return;
    }

    upload(
      { documentType: documentType as DocumentTypeValue, file: selectedFile },
      {
        onSuccess: () => {
          handleClose();
          onSuccess();
        },
        onError: () => {},
      }
    );
  };

  const isValid = documentType && selectedFile && !isPending;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={handleClose}
    >
      <View style={styles.overlay}>
        <View style={styles.modal}>
          <View style={styles.header}>
            <Text style={styles.title}>Upload Document</Text>
            <TouchableOpacity onPress={handleClose} style={styles.closeBtn}>
              <Ionicons name="close" size={24} color={Colors.text} />
            </TouchableOpacity>
          </View>

          <ScrollView style={styles.content} keyboardShouldPersistTaps="handled">
            {/* Document Type */}
            <Text style={styles.label}>Document Type</Text>
            <TouchableOpacity
              style={styles.picker}
              onPress={() => setShowTypePicker(!showTypePicker)}
            >
              <Text style={documentType ? styles.pickerText : styles.pickerPlaceholder}>
                {documentType
                  ? DOCUMENT_TYPE_LABELS[documentType]
                  : "Select document type"}
              </Text>
              <Ionicons
                name={showTypePicker ? "chevron-up" : "chevron-down"}
                size={20}
                color={Colors.textSecondary}
              />
            </TouchableOpacity>
            {showTypePicker && (
              <View style={styles.pickerOptions}>
                {DOCUMENT_TYPES.map((type) => (
                  <TouchableOpacity
                    key={type}
                    style={styles.pickerOption}
                    onPress={() => {
                      setDocumentType(type);
                      setShowTypePicker(false);
                    }}
                  >
                    <Text style={styles.pickerOptionText}>
                      {DOCUMENT_TYPE_LABELS[type]}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            )}

            {/* File Picker */}
            <Text style={[styles.label, { marginTop: Spacing.md }]}>File</Text>
            <TouchableOpacity style={styles.fileButton} onPress={handlePickFile}>
              <Ionicons name="document-attach-outline" size={24} color={Colors.primary} />
              <Text style={styles.fileButtonText}>
                {selectedFile ? selectedFile.name : "Choose PDF or Image"}
              </Text>
            </TouchableOpacity>

            {error && (
              <View style={styles.errorBox}>
                <Ionicons name="alert-circle" size={18} color={Colors.error} />
                <Text style={styles.errorText}>
                  {typeof error === 'object' && error !== null && 'data' in error
                    ? (error as { data?: { message?: string } }).data?.message ||
                      (typeof (error as Error).message === 'string' &&
                      (error as Error).message !== 'true'
                        ? (error as Error).message
                        : 'Upload failed. Please check your file (PDF, JPG, PNG, max 10 MB) and try again.')
                    : typeof (error as Error).message === 'string' &&
                      (error as Error).message !== 'true'
                    ? (error as Error).message
                    : 'Upload failed. Please check your file (PDF, JPG, PNG, max 10 MB) and try again.'}
                </Text>
              </View>
            )}
          </ScrollView>

          <View style={styles.footer}>
            <TouchableOpacity style={styles.cancelButton} onPress={handleClose}>
              <Text style={styles.cancelButtonText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.uploadButton, !isValid && styles.uploadButtonDisabled]}
              onPress={handleUpload}
              disabled={!isValid}
            >
              {isPending ? (
                <ActivityIndicator size="small" color="#FFFFFF" />
              ) : (
                <Text style={styles.uploadButtonText}>Upload</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "flex-end",
  },
  modal: {
    backgroundColor: Colors.background,
    borderTopLeftRadius: Layout.borderRadius.lg,
    borderTopRightRadius: Layout.borderRadius.lg,
    maxHeight: "80%",
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: Spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  title: {
    fontSize: 18,
    fontWeight: "600",
    color: Colors.text,
  },
  closeBtn: {
    padding: Spacing.xs,
  },
  content: {
    padding: Spacing.lg,
  },
  label: {
    fontSize: 14,
    fontWeight: "500",
    color: Colors.textSecondary,
    marginBottom: Spacing.xs,
  },
  picker: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: Spacing.md,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.sm,
    borderWidth: 1,
    borderColor: Colors.borderLight,
  },
  pickerText: {
    fontSize: 16,
    color: Colors.text,
  },
  pickerPlaceholder: {
    fontSize: 16,
    color: Colors.textTertiary,
  },
  pickerOptions: {
    marginTop: Spacing.xs,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.sm,
    borderWidth: 1,
    borderColor: Colors.borderLight,
    overflow: "hidden",
  },
  pickerOption: {
    padding: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  pickerOptionText: {
    fontSize: 16,
    color: Colors.text,
  },
  fileButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.md,
    padding: Spacing.md,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.sm,
    borderWidth: 1,
    borderColor: Colors.borderLight,
    borderStyle: "dashed",
  },
  fileButtonText: {
    fontSize: 16,
    color: Colors.primary,
    flex: 1,
  },
  errorBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.sm,
    marginTop: Spacing.md,
    padding: Spacing.md,
    backgroundColor: "#FFF5F5",
    borderRadius: Layout.borderRadius.sm,
    borderWidth: 1,
    borderColor: "#FFCCCC",
  },
  errorText: {
    flex: 1,
    fontSize: 14,
    color: Colors.error,
  },
  footer: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: Spacing.md,
    padding: Spacing.lg,
    borderTopWidth: 1,
    borderTopColor: Colors.borderLight,
  },
  cancelButton: {
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
  },
  cancelButtonText: {
    fontSize: 16,
    color: Colors.textSecondary,
  },
  uploadButton: {
    paddingHorizontal: Spacing.xl,
    paddingVertical: Spacing.md,
    backgroundColor: Colors.primary,
    borderRadius: Layout.borderRadius.sm,
    minWidth: 100,
    alignItems: "center",
  },
  uploadButtonDisabled: {
    opacity: 0.5,
  },
  uploadButtonText: {
    fontSize: 16,
    fontWeight: "600",
    color: "#FFFFFF",
  },
});
