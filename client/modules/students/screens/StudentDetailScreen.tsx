import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
  SafeAreaView,
  ScrollView,
  TouchableOpacity,
  Alert,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useStudents } from "../hooks/useStudents";
import { usePermissions } from "@/modules/permissions/hooks/usePermissions";
import * as PERMS from "@/modules/permissions/constants/permissions";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";
import { CreateStudentModal } from "../components/CreateStudentModal";
import { StudentDocumentsSection } from "../components/StudentDocumentsSection";

export default function StudentDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { currentStudent, loading, fetchStudent, updateStudent, deleteStudent } = useStudents();
  const { hasPermission } = usePermissions();
  const [editModalVisible, setEditModalVisible] = useState(false);

  const canUpdate = hasPermission(PERMS.STUDENT_UPDATE);
  const canDelete = hasPermission(PERMS.STUDENT_DELETE);

  useEffect(() => {
    if (id) {
      fetchStudent(id);
    }
  }, [id]);

  const handleUpdate = async (data: any) => {
    if (!id) return;

    try {
      await updateStudent(id, data);
      setEditModalVisible(false);
      Alert.alert("Success", "Student updated successfully");
      // Refresh data
      fetchStudent(id);
    } catch (error: any) {
      throw error;
    }
  };

  const handleBack = () => {
    router.back();
  };

  if (loading && !currentStudent) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.center}>
          <ActivityIndicator size="large" color={Colors.primary} />
        </View>
      </SafeAreaView>
    );
  }

  if (!currentStudent) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.center}>
          <Text style={styles.errorText}>Student not found</Text>
          <TouchableOpacity style={styles.backButton} onPress={handleBack}>
            <Text style={styles.backButtonText}>Go Back</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity onPress={handleBack} style={styles.backIcon}>
          <Ionicons name="arrow-back" size={24} color={Colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Student Details</Text>
        {canDelete && (
          <TouchableOpacity
            style={styles.deleteButton}
            onPress={() => {deleteStudent(currentStudent.id)
              Alert.alert("Success", "Student deleted successfully");
              router.replace("/students");
            }}
          >
            <Ionicons name="trash-outline" size={24} color={Colors.error} />
          </TouchableOpacity>
        )}
        {canUpdate && (
          <TouchableOpacity
            style={styles.editButton}
            onPress={() => setEditModalVisible(true)}
          >
            <Ionicons name="create-outline" size={24} color={Colors.primary} />
          </TouchableOpacity>
        )}
      </View>

      <ScrollView style={styles.content}>
        {/* Basic Information */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Basic Information</Text>
          
          <View style={styles.infoRow}>
            <Text style={styles.label}>Full Name</Text>
            <Text style={styles.value}>{currentStudent.name}</Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.label}>Admission Number</Text>
            <Text style={styles.value}>{currentStudent.admission_number}</Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.label}>Academic Year</Text>
            <Text style={styles.value}>
              {currentStudent.academic_year || "Not set"}
            </Text>
          </View>

          {currentStudent.gender && (
            <View style={styles.infoRow}>
              <Text style={styles.label}>Gender</Text>
              <Text style={styles.value}>{currentStudent.gender}</Text>
            </View>
          )}

          {currentStudent.date_of_birth && (
            <View style={styles.infoRow}>
              <Text style={styles.label}>Date of Birth</Text>
              <Text style={styles.value}>{currentStudent.date_of_birth}</Text>
            </View>
          )}
        </View>

        {/* Contact Information */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Contact Information</Text>

          {currentStudent.email && (
            <View style={styles.infoRow}>
              <Text style={styles.label}>Email</Text>
              <Text style={styles.value}>{currentStudent.email}</Text>
            </View>
          )}

          {currentStudent.phone && (
            <View style={styles.infoRow}>
              <Text style={styles.label}>Phone</Text>
              <Text style={styles.value}>{currentStudent.phone}</Text>
            </View>
          )}

          {currentStudent.address && (
            <View style={styles.infoRow}>
              <Text style={styles.label}>Address</Text>
              <Text style={styles.value}>{currentStudent.address}</Text>
            </View>
          )}
        </View>

        {/* Guardian Information */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Guardian Information</Text>

          {currentStudent.guardian_name && (
            <View style={styles.infoRow}>
              <Text style={styles.label}>Guardian Name</Text>
              <Text style={styles.value}>{currentStudent.guardian_name}</Text>
            </View>
          )}

          {currentStudent.guardian_relationship && (
            <View style={styles.infoRow}>
              <Text style={styles.label}>Relationship</Text>
              <Text style={styles.value}>{currentStudent.guardian_relationship}</Text>
            </View>
          )}

          {currentStudent.guardian_phone && (
            <View style={styles.infoRow}>
              <Text style={styles.label}>Guardian Phone</Text>
              <Text style={styles.value}>{currentStudent.guardian_phone}</Text>
            </View>
          )}

          {currentStudent.guardian_email && (
            <View style={styles.infoRow}>
              <Text style={styles.label}>Guardian Email</Text>
              <Text style={styles.value}>{currentStudent.guardian_email}</Text>
            </View>
          )}
        </View>

        {/* Class Information */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Class Information</Text>

          <View style={styles.infoRow}>
            <Text style={styles.label}>Current Class</Text>
            <Text style={styles.value}>
              {currentStudent.class_name || "Not Assigned"}
            </Text>
          </View>

          {currentStudent.roll_number && (
            <View style={styles.infoRow}>
              <Text style={styles.label}>Roll Number</Text>
              <Text style={styles.value}>{currentStudent.roll_number}</Text>
            </View>
          )}
        </View>

        {/* Documents */}
        <StudentDocumentsSection studentId={currentStudent.id} />
      </ScrollView>

      {/* Edit Modal */}
      {canUpdate && (
        <CreateStudentModal
          visible={editModalVisible}
          onClose={() => setEditModalVisible(false)}
          onSubmit={handleUpdate}
          initialData={currentStudent}
          mode="edit"
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.background,
  },
  center: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: Spacing.xl,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: Spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
    backgroundColor: Colors.background,
  },
  backIcon: {
    padding: Spacing.sm,
  },
  headerTitle: {
    flex: 1,
    fontSize: 20,
    fontWeight: "bold",
    color: Colors.text,
    marginLeft: Spacing.md,
  },
  editButton: {
    padding: Spacing.sm,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.md,
  },
  deleteButton: {
    padding: Spacing.sm,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.md,
  },
  content: {
    flex: 1,
    padding: Spacing.lg,
  },
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
  sectionTitle: {
    fontSize: 18,
    fontWeight: "600",
    color: Colors.text,
    marginBottom: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
    paddingBottom: Spacing.sm,
  },
  infoRow: {
    marginBottom: Spacing.md,
  },
  label: {
    fontSize: 14,
    color: Colors.textSecondary,
    marginBottom: 4,
  },
  value: {
    fontSize: 16,
    fontWeight: "500",
    color: Colors.text,
  },
  errorText: {
    fontSize: 16,
    color: Colors.error,
    textAlign: "center",
    marginBottom: Spacing.lg,
  },
  backButton: {
    backgroundColor: Colors.primary,
    paddingHorizontal: Spacing.xl,
    paddingVertical: Spacing.md,
    borderRadius: Layout.borderRadius.md,
  },
  backButtonText: {
    color: "#FFFFFF",
    fontSize: 16,
    fontWeight: "600",
  },
});
