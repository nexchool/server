/**
 * StudentDocumentsSection
 * Renders document list, empty state, Add Document button, and document cards.
 * Tapping a card opens the URL in the browser.
 */
import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Linking,
  ActivityIndicator,
  Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  useStudentDocuments,
  useUploadStudentDocument,
  useDeleteStudentDocument,
} from "../hooks/useStudentDocuments";
import { usePermissions } from "@/modules/permissions/hooks/usePermissions";
import * as PERMS from "@/modules/permissions/constants/permissions";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";
import { StudentDocument, DOCUMENT_TYPE_LABELS } from "../types";
import { UploadDocumentModal } from "./UploadDocumentModal";

interface StudentDocumentsSectionProps {
  studentId: string;
}

export function StudentDocumentsSection({ studentId }: StudentDocumentsSectionProps) {
  const {
    data: documents,
    isLoading,
    isError,
    refetch,
  } = useStudentDocuments(studentId);
  const uploadMutation = useUploadStudentDocument(studentId);
  const deleteMutation = useDeleteStudentDocument(studentId);
  const { hasPermission } = usePermissions();
  const [uploadModalVisible, setUploadModalVisible] = useState(false);

  const canManage = hasPermission(PERMS.STUDENT_MANAGE);

  const handleDeleteDocument = (doc: StudentDocument) => {
    Alert.alert(
      "Delete Document",
      `Are you sure you want to delete "${doc.original_filename}"?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => {
            deleteMutation.mutate(doc.id, {
              onError: (err) => {
                Alert.alert("Error", err.message);
              },
            });
          },
        },
      ]
    );
  };

  const handleOpenDocument = (doc: StudentDocument) => {
    if (doc.cloudinary_url) {
      Linking.openURL(doc.cloudinary_url);
    }
  };

  const handleUploadSuccess = () => {
    setUploadModalVisible(false);
    refetch();
  };

  if (isLoading) {
    return (
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Documents</Text>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="small" color={Colors.primary} />
        </View>
      </View>
    );
  }

  const list = Array.isArray(documents) ? documents : [];

  if (isError) {
    return (
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Documents</Text>
        <View style={styles.errorContainer}>
          <Text style={styles.errorMessage}>
            Unable to load documents. You can add documents below to complete the
            profile, or tap Retry to try again.
          </Text>
          <View style={styles.errorActions}>
            <TouchableOpacity style={styles.retryButton} onPress={() => refetch()}>
              <Ionicons name="refresh" size={18} color={Colors.primary} />
              <Text style={styles.retryButtonText}>Retry</Text>
            </TouchableOpacity>
            {canManage && (
              <TouchableOpacity
                style={styles.addFromErrorButton}
                onPress={() => setUploadModalVisible(true)}
              >
                <Ionicons name="add" size={18} color={Colors.primary} />
                <Text style={styles.retryButtonText}>Add Document</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>
        <UploadDocumentModal
          visible={uploadModalVisible}
          onClose={() => setUploadModalVisible(false)}
          onSuccess={handleUploadSuccess}
          studentId={studentId}
          uploadMutation={uploadMutation}
        />
      </View>
    );
  }

  return (
    <View style={styles.section}>
      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Documents</Text>
        {canManage && (
          <TouchableOpacity
            style={styles.addButton}
            onPress={() => setUploadModalVisible(true)}
          >
            <Ionicons name="add" size={20} color={Colors.primary} />
            <Text style={styles.addButtonText}>Add Document</Text>
          </TouchableOpacity>
        )}
      </View>

      {list.length === 0 ? (
        <View style={styles.emptyState}>
          <Ionicons name="document-outline" size={48} color={Colors.textSecondary} />
          <Text style={styles.emptyText}>
            No documents uploaded yet. Tap + to add the first one.
          </Text>
          {canManage && (
            <TouchableOpacity
              style={styles.emptyAddButton}
              onPress={() => setUploadModalVisible(true)}
            >
              <Text style={styles.emptyAddButtonText}>Add Document</Text>
            </TouchableOpacity>
          )}
        </View>
      ) : (
        <View style={styles.docList}>
          {list.map((doc) => (
            <TouchableOpacity
              key={doc.id}
              style={styles.docCard}
              onPress={() => handleOpenDocument(doc)}
              onLongPress={() => canManage && handleDeleteDocument(doc)}
              activeOpacity={0.7}
              delayLongPress={400}
            >
              <Ionicons
                name={doc.mime_type?.startsWith("image") ? "image-outline" : "document-outline"}
                size={24}
                color={Colors.primary}
              />
              <View style={styles.docCardContent}>
                <Text style={styles.docCardLabel}>
                  {doc.document_type_label || DOCUMENT_TYPE_LABELS[doc.document_type] || doc.document_type}
                </Text>
                <Text style={styles.docCardFilename} numberOfLines={1}>
                  {doc.original_filename}
                </Text>
                <Text style={styles.docCardDate}>
                  {doc.created_at
                    ? new Date(doc.created_at).toLocaleDateString()
                    : ""}
                </Text>
              </View>
              {canManage && (
                <TouchableOpacity
                  style={styles.deleteIconButton}
                  onPress={(e) => {
                    e.stopPropagation();
                    handleDeleteDocument(doc);
                  }}
                  hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                >
                  <Ionicons name="trash-outline" size={20} color={Colors.error} />
                </TouchableOpacity>
              )}
              <Ionicons name="open-outline" size={20} color={Colors.textSecondary} />
            </TouchableOpacity>
          ))}
        </View>
      )}

      <UploadDocumentModal
        visible={uploadModalVisible}
        onClose={() => setUploadModalVisible(false)}
        onSuccess={handleUploadSuccess}
        studentId={studentId}
        uploadMutation={uploadMutation}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    marginBottom: Spacing.xl,
    backgroundColor: Colors.background,
    borderRadius: Layout.borderRadius.md,
    borderWidth: 1,
    borderColor: Colors.borderLight,
    padding: Spacing.lg,
    shadowColor: Colors.shadow,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 2,
  },
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: Spacing.md,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "600",
    color: Colors.text,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
    paddingBottom: Spacing.sm,
  },
  addButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.xs,
    paddingHorizontal: Spacing.sm,
    paddingVertical: Spacing.xs,
  },
  addButtonText: {
    fontSize: 14,
    color: Colors.primary,
    fontWeight: "500",
  },
  loadingContainer: {
    padding: Spacing.xl,
    alignItems: "center",
  },
  errorContainer: {
    padding: Spacing.xl,
    alignItems: "center",
  },
  errorText: {
    fontSize: 14,
    color: Colors.error,
    marginBottom: Spacing.md,
  },
  retryButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.xs,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.sm,
  },
  retryButtonText: {
    fontSize: 14,
    color: Colors.primary,
    fontWeight: "500",
  },
  emptyState: {
    alignItems: "center",
    paddingVertical: Spacing.xl,
  },
  emptyText: {
    fontSize: 14,
    color: Colors.textSecondary,
    textAlign: "center",
    marginTop: Spacing.md,
  },
  emptyAddButton: {
    marginTop: Spacing.md,
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.sm,
    backgroundColor: Colors.primary,
    borderRadius: Layout.borderRadius.sm,
  },
  emptyAddButtonText: {
    color: "#FFFFFF",
    fontSize: 14,
    fontWeight: "600",
  },
  docList: {
    gap: Spacing.sm,
  },
  docCard: {
    flexDirection: "row",
    alignItems: "center",
    padding: Spacing.md,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.sm,
    borderWidth: 1,
    borderColor: Colors.borderLight,
  },
  docCardContent: {
    flex: 1,
    marginLeft: Spacing.md,
  },
  docCardLabel: {
    fontSize: 15,
    fontWeight: "600",
    color: Colors.text,
  },
  docCardFilename: {
    fontSize: 13,
    color: Colors.textSecondary,
    marginTop: 2,
  },
  docCardDate: {
    fontSize: 12,
    color: Colors.textTertiary,
    marginTop: 2,
  },
  deleteIconButton: {
    padding: Spacing.xs,
    marginRight: Spacing.sm,
  },
});
