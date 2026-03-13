import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";
import { CreateClassDTO } from "../types";
import { DateField } from "@/common/components/DateField";
import { useAcademicYears } from "@/modules/academics/hooks/useAcademicYears";
import { useAcademicYearContext } from "@/modules/academics/context/AcademicYearContext";
import { classService } from "@/modules/classes/services/classService";
import { Teacher } from "@/modules/teachers/types";

interface EditInitialData {
  name: string;
  section: string;
  academic_year_id: string;
  teacher_id?: string;
  start_date?: string;
  end_date?: string;
}

interface Props {
  visible: boolean;
  onClose: () => void;
  onSubmit: (data: CreateClassDTO) => Promise<void>;
  /** When provided, modal acts as Edit mode with pre-filled form. Pass classId for teacher picker. */
  initialData?: EditInitialData;
  classId?: string;
}

export const CreateClassModal: React.FC<Props> = ({
  visible,
  onClose,
  onSubmit,
  initialData,
  classId,
}) => {
  const isEditMode = !!initialData;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [section, setSection] = useState("");
  const [academicYearId, setAcademicYearId] = useState("");
  const [classTeacherId, setClassTeacherId] = useState<string>("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const { data: academicYears = [], isLoading: academicYearsLoading } = useAcademicYears(false);
  const { selectedAcademicYearId: contextYearId } = useAcademicYearContext();
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [teachersLoading, setTeachersLoading] = useState(false);

  useEffect(() => {
    if (visible) {
      if (initialData) {
        setName(initialData.name);
        setSection(initialData.section);
        setAcademicYearId(initialData.academic_year_id);
        setClassTeacherId(initialData.teacher_id || "");
        setStartDate(initialData.start_date || "");
        setEndDate(initialData.end_date || "");
      }
      setTeachersLoading(true);
      classService
        .getAvailableClassTeachers(classId)
        .then(setTeachers)
        .finally(() => setTeachersLoading(false));
      if (!initialData) {
        setAcademicYearId(contextYearId || "");
      }
    }
  }, [visible, contextYearId, initialData, classId]);

  const resetForm = () => {
    if (initialData) {
      setName(initialData.name);
      setSection(initialData.section);
      setAcademicYearId(initialData.academic_year_id);
      setClassTeacherId(initialData.teacher_id || "");
      setStartDate(initialData.start_date || "");
      setEndDate(initialData.end_date || "");
    } else {
      setName("");
      setSection("");
      setAcademicYearId(contextYearId || "");
      setClassTeacherId("");
      setStartDate("");
      setEndDate("");
    }
    setError(null);
  };

  const handleSubmit = async () => {
    if (!name.trim() || !section.trim() || !academicYearId) {
      setError("Class name, section, and academic year are required");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      await onSubmit({
        name: name.trim(),
        section: section.trim(),
        academic_year_id: academicYearId,
        teacher_id: classTeacherId || undefined,
        start_date: startDate.trim() || undefined,
        end_date: endDate.trim() || undefined,
      });
      resetForm();
    } catch (err: any) {
      setError(err.message || (isEditMode ? "Failed to update class" : "Failed to create class"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet">
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={onClose} style={styles.closeButton}>
            <Ionicons name="close" size={24} color={Colors.text} />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>{isEditMode ? "Edit Class" : "Create Class"}</Text>
          <View style={{ width: 40 }} />
        </View>

        <ScrollView style={styles.form} showsVerticalScrollIndicator={false}>
          {error && (
            <View style={styles.errorContainer}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}

          <View style={styles.fieldContainer}>
            <Text style={styles.fieldLabel}>Class Name *</Text>
            <TextInput
              style={styles.input}
              value={name}
              onChangeText={setName}
              placeholder="e.g. Grade 10"
              placeholderTextColor={Colors.textTertiary}
            />
          </View>

          <View style={styles.fieldContainer}>
            <Text style={styles.fieldLabel}>Section *</Text>
            <TextInput
              style={styles.input}
              value={section}
              onChangeText={setSection}
              placeholder="e.g. A"
              placeholderTextColor={Colors.textTertiary}
            />
          </View>

          <View style={styles.fieldContainer}>
            <Text style={styles.fieldLabel}>Academic Year *</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow}>
              {academicYearsLoading ? (
                <Text style={styles.placeholderText}>Loading...</Text>
              ) : academicYears.length === 0 ? (
                <Text style={styles.placeholderText}>No academic years. Create one in Finance.</Text>
              ) : (
                academicYears.map((ay) => (
                  <TouchableOpacity
                    key={ay.id}
                    style={[styles.chip, academicYearId === ay.id && styles.chipActive]}
                    onPress={() => setAcademicYearId(ay.id)}
                  >
                    <Text style={[styles.chipText, academicYearId === ay.id && styles.chipTextActive]}>
                      {ay.name}
                    </Text>
                  </TouchableOpacity>
                ))
              )}
            </ScrollView>
          </View>

          <View style={styles.fieldContainer}>
            <Text style={styles.fieldLabel}>Class Teacher (optional)</Text>
            <Text style={styles.fieldHint}>Only the class teacher can mark attendance for this class.</Text>
            {teachersLoading ? (
              <ActivityIndicator size="small" color={Colors.primary} style={styles.teacherLoader} />
            ) : (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow}>
                <TouchableOpacity
                  style={[styles.chip, !classTeacherId && styles.chipActive]}
                  onPress={() => setClassTeacherId("")}
                >
                  <Text style={[styles.chipText, !classTeacherId && styles.chipTextActive]}>None</Text>
                </TouchableOpacity>
                {teachers.map((t) => (
                  <TouchableOpacity
                    key={t.id}
                    style={[styles.chip, classTeacherId === t.user_id && styles.chipActive]}
                    onPress={() => setClassTeacherId(classTeacherId === t.user_id ? "" : t.user_id)}
                  >
                    <Text
                      style={[
                        styles.chipText,
                        classTeacherId === t.user_id && styles.chipTextActive,
                      ]}
                      numberOfLines={1}
                    >
                      {t.name} ({t.employee_id})
                    </Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
            )}
          </View>

          <View style={styles.fieldContainer}>
            <DateField
              label="Start Date"
              value={startDate}
              onChange={setStartDate}
              placeholder="YYYY-MM-DD"
              useOverlayInsideModal
            />
          </View>

          <View style={styles.fieldContainer}>
            <DateField
              label="End Date"
              value={endDate}
              onChange={setEndDate}
              placeholder="YYYY-MM-DD"
              useOverlayInsideModal
            />
          </View>

          <TouchableOpacity
            style={[styles.submitButton, loading && styles.submitButtonDisabled]}
            onPress={handleSubmit}
            disabled={loading}
          >
            {loading ? (
              <ActivityIndicator color="#FFFFFF" />
            ) : (
              <Text style={styles.submitButtonText}>{isEditMode ? "Update Class" : "Create Class"}</Text>
            )}
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.background,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: Spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  closeButton: {
    padding: Spacing.sm,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: "600",
    color: Colors.text,
  },
  form: {
    flex: 1,
    padding: Spacing.lg,
  },
  fieldContainer: {
    marginBottom: Spacing.md,
  },
  fieldLabel: {
    fontSize: 14,
    fontWeight: "500",
    color: Colors.text,
    marginBottom: Spacing.xs,
  },
  fieldHint: {
    fontSize: 12,
    color: Colors.textTertiary,
    marginBottom: Spacing.sm,
  },
  teacherLoader: {
    marginVertical: Spacing.sm,
  },
  input: {
    borderWidth: 1,
    borderColor: Colors.borderLight,
    borderRadius: Layout.borderRadius.sm,
    padding: Spacing.md,
    fontSize: 16,
    color: Colors.text,
    backgroundColor: Colors.backgroundSecondary,
  },
  errorContainer: {
    backgroundColor: "#FFF0F0",
    padding: Spacing.md,
    borderRadius: Layout.borderRadius.sm,
    marginBottom: Spacing.md,
    borderLeftWidth: 4,
    borderLeftColor: Colors.error,
  },
  errorText: {
    color: Colors.error,
    fontSize: 14,
  },
  submitButton: {
    backgroundColor: Colors.primary,
    padding: Spacing.md,
    borderRadius: Layout.borderRadius.md,
    alignItems: "center",
    marginTop: Spacing.lg,
  },
  submitButtonDisabled: {
    opacity: 0.6,
  },
  submitButtonText: {
    color: "#FFFFFF",
    fontSize: 16,
    fontWeight: "600",
  },
  chipRow: { marginBottom: Spacing.xs },
  chip: {
    paddingVertical: Spacing.sm,
    paddingHorizontal: Spacing.md,
    marginRight: Spacing.sm,
    borderRadius: Layout.borderRadius.sm,
    borderWidth: 1,
    borderColor: Colors.borderLight,
    backgroundColor: Colors.backgroundSecondary,
  },
  chipActive: {
    borderColor: Colors.primary,
    backgroundColor: Colors.primary + "20",
  },
  chipText: { fontSize: 14, color: Colors.text },
  chipTextActive: { color: Colors.primary, fontWeight: "600" },
  placeholderText: { fontSize: 14, color: Colors.textTertiary, paddingVertical: Spacing.sm },
});
