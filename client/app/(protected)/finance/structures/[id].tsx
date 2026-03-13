import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  SafeAreaView,
  Modal,
  TextInput,
  Switch,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import {
  useStructure,
  useAcademicYears,
  useAvailableClassesForStructure,
  useUpdateStructure,
  useDeleteStructure,
} from "@/modules/finance/hooks/useFinance";
import type { FeeStructure } from "@/modules/finance/types";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";
import { ClassMultiSelect } from "@/common/components/ClassMultiSelect";
import { DateField } from "@/common/components/DateField";

function formatDate(s: string) {
  try {
    return new Date(s).toLocaleDateString("en-IN");
  } catch {
    return s;
  }
}

function formatCurrency(n: number) {
  return `₹${n.toLocaleString("en-IN")}`;
}

export default function FeeStructureInfoPage() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [modalOpen, setModalOpen] = useState(false);

  const { data: structure, isLoading, error, refetch } = useStructure(id);
  const { data: academicYears = [] } = useAcademicYears(false);

  const updateMut = useUpdateStructure();
  const deleteMut = useDeleteStructure();

  const academicYearName =
    academicYears.find((ay) => ay.id === structure?.academic_year_id)?.name ?? structure?.academic_year_id ?? "—";

  const handleEdit = () => setModalOpen(true);

  const handleDelete = () => {
    if (!structure) return;
    Alert.alert(
      "Delete Structure",
      `Delete "${structure.name}"? This cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            try {
              await deleteMut.mutateAsync(structure.id);
              router.back();
            } catch (e: unknown) {
              Alert.alert("Error", e instanceof Error ? e.message : "Failed to delete");
            }
          },
        },
      ]
    );
  };

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.errorText}>
          {error instanceof Error ? error.message : "Failed to load"}
        </Text>
        <TouchableOpacity style={styles.retryBtn} onPress={() => refetch()}>
          <Text style={styles.retryBtnText}>Retry</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (isLoading || !structure) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={Colors.primary} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backIcon}>
          <Ionicons name="arrow-back" size={24} color={Colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Fee Structure</Text>
        <View style={styles.headerActions}>
          <TouchableOpacity onPress={handleDelete} style={styles.headerIconBtn}>
            <Ionicons name="trash-outline" size={24} color={Colors.error} />
          </TouchableOpacity>
          <TouchableOpacity onPress={handleEdit} style={styles.headerIconBtn}>
            <Ionicons name="create-outline" size={24} color={Colors.primary} />
          </TouchableOpacity>
        </View>
      </View>

      <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
        <View style={styles.card}>
          <Text style={styles.cardTitle}>{structure.name}</Text>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Academic Year</Text>
          <Text style={styles.sectionValue}>{academicYearName}</Text>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Due Date</Text>
          <Text style={styles.sectionValue}>{formatDate(structure.due_date)}</Text>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Classes</Text>
          <Text style={styles.sectionValue}>
            {structure.class_name ?? "All classes"}
          </Text>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Components</Text>
          {structure.components?.length ? (
            <View style={styles.componentsList}>
              {structure.components.map((c) => (
                <View key={c.id} style={styles.componentRow}>
                  <Text style={styles.componentName}>
                    {c.name} {c.is_optional ? "(optional)" : ""}
                  </Text>
                  <Text style={styles.componentAmount}>{formatCurrency(c.amount)}</Text>
                </View>
              ))}
            </View>
          ) : (
            <Text style={styles.emptyText}>No components</Text>
          )}
        </View>
      </ScrollView>

      {modalOpen && (
        <StructureEditModal
          visible={modalOpen}
          onClose={() => setModalOpen(false)}
          structure={structure}
          academicYears={academicYears}
          onUpdate={async (data) => {
            await updateMut.mutateAsync({ id: structure.id, data });
            setModalOpen(false);
          }}
          isUpdating={updateMut.isPending}
        />
      )}
    </SafeAreaView>
  );
}

interface StructureEditModalProps {
  visible: boolean;
  onClose: () => void;
  structure: FeeStructure;
  academicYears: { id: string; name: string }[];
  onUpdate: (data: { name?: string; due_date?: string; class_ids?: string[]; components?: { name: string; amount: number; is_optional: boolean }[] }) => Promise<void>;
  isUpdating: boolean;
}

function StructureEditModal({
  visible,
  onClose,
  structure,
  academicYears,
  onUpdate,
  isUpdating,
}: StructureEditModalProps) {
  const [name, setName] = useState(structure.name ?? "");
  const [classIds, setClassIds] = useState<string[]>(structure.class_ids ?? []);
  const [dueDate, setDueDate] = useState(structure.due_date ?? "");
  const [components, setComponents] = useState<{ name: string; amount: string; is_optional: boolean }[]>(
    structure.components?.map((c) => ({
      name: c.name,
      amount: String(c.amount ?? 0),
      is_optional: c.is_optional ?? false,
    })) ?? []
  );

  React.useEffect(() => {
    if (visible) {
      setName(structure.name ?? "");
      setClassIds(structure.class_ids ?? []);
      setDueDate(structure.due_date ?? "");
      setComponents(
        structure.components?.map((c) => ({
          name: c.name,
          amount: String(c.amount ?? 0),
          is_optional: c.is_optional ?? false,
        })) ?? []
      );
    }
  }, [visible, structure]);

  const { data: availableClasses = [] } = useAvailableClassesForStructure(
    structure.academic_year_id,
    structure.id,
    visible
  );
  const classOptions = availableClasses.map((c) => ({
    id: c.id,
    label: c.section ? `${c.name}-${c.section}` : c.name,
    name: c.name,
    section: c.section,
  }));

  const addComponent = () => {
    setComponents([...components, { name: "", amount: "", is_optional: false }]);
  };

  const removeComponent = (i: number) => {
    if (components.length <= 1) return;
    setComponents(components.filter((_, idx) => idx !== i));
  };

  const updateComponent = (i: number, field: string, value: string | boolean) => {
    const next = [...components];
    if (field === "name") next[i] = { ...next[i], name: value as string };
    else if (field === "amount") next[i] = { ...next[i], amount: value as string };
    else if (field === "is_optional") next[i] = { ...next[i], is_optional: value as boolean };
    setComponents(next);
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      Alert.alert("Error", "Name is required");
      return;
    }
    if (!dueDate.trim()) {
      Alert.alert("Error", "Due date is required");
      return;
    }
    const comps = components
      .filter((c) => c.name.trim() && c.amount.trim())
      .map((c) => ({
        name: c.name.trim(),
        amount: parseFloat(c.amount) || 0,
        is_optional: c.is_optional,
      }));
    if (comps.length === 0) {
      Alert.alert("Error", "At least one component is required");
      return;
    }
    try {
      await onUpdate({
        name: name.trim(),
        due_date: dueDate.trim(),
        class_ids: classIds,
        components: comps,
      });
    } catch (e: unknown) {
      Alert.alert("Error", e instanceof Error ? e.message : "Failed to save");
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent>
      <View style={styles.modalOverlay}>
        <View style={styles.modalContent}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Edit Structure</Text>
            <TouchableOpacity onPress={onClose}>
              <Ionicons name="close" size={24} color={Colors.text} />
            </TouchableOpacity>
          </View>
          <ScrollView style={styles.modalBody} showsVerticalScrollIndicator={false}>
            <Text style={styles.inputLabel}>Structure name</Text>
            <TextInput
              style={styles.input}
              value={name}
              onChangeText={setName}
              placeholder="e.g. Term 1 Fee 2025"
            />
            <Text style={styles.inputLabel}>Classes</Text>
            <ClassMultiSelect
              value={classIds}
              onChange={setClassIds}
              options={classOptions}
              placeholder="All classes"
            />
            <DateField
              label="Due Date"
              value={dueDate}
              onChange={setDueDate}
              placeholder="e.g. 2025-03-31"
            />
            <View style={styles.componentHeader}>
              <Text style={styles.inputLabel}>Components</Text>
              <TouchableOpacity onPress={addComponent} style={styles.addComponentBtn}>
                <Ionicons name="add" size={20} color={Colors.primary} />
                <Text style={styles.addComponentText}>Add</Text>
              </TouchableOpacity>
            </View>
            {components.map((c, i) => (
              <View key={i} style={styles.componentFormRow}>
                <TextInput
                  style={[styles.input, styles.componentInput]}
                  value={c.name}
                  onChangeText={(v) => updateComponent(i, "name", v)}
                  placeholder="Component name"
                />
                <TextInput
                  style={[styles.input, styles.amountInput]}
                  value={c.amount}
                  onChangeText={(v) => updateComponent(i, "amount", v)}
                  placeholder="Amount"
                  keyboardType="decimal-pad"
                />
                <View style={styles.optionalRow}>
                  <Text style={styles.optionalLabel}>Optional</Text>
                  <Switch
                    value={c.is_optional}
                    onValueChange={(v) => updateComponent(i, "is_optional", v)}
                  />
                </View>
                <TouchableOpacity
                  onPress={() => removeComponent(i)}
                  disabled={components.length <= 1}
                  style={styles.removeBtn}
                >
                  <Ionicons name="remove-circle-outline" size={22} color={Colors.error} />
                </TouchableOpacity>
              </View>
            ))}
          </ScrollView>
          <View style={styles.modalFooter}>
            <TouchableOpacity style={styles.cancelBtn} onPress={onClose}>
              <Text style={styles.cancelBtnText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.submitBtn, isUpdating && styles.submitBtnDisabled]}
              onPress={handleSubmit}
              disabled={isUpdating}
            >
              {isUpdating ? (
                <ActivityIndicator size="small" color={Colors.background} />
              ) : (
                <Text style={styles.submitBtnText}>Update</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  backIcon: { padding: Spacing.sm, marginRight: Spacing.sm },
  headerTitle: { flex: 1, fontSize: 22, fontWeight: "bold", color: Colors.text },
  headerActions: { flexDirection: "row", gap: Spacing.sm, alignItems: "center" },
  headerIconBtn: {
    padding: Spacing.sm,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.md,
  },
  actionLabel: { fontSize: 11, color: Colors.primary, marginTop: 2 },
  actionBtnDanger: {},
  actionLabelDanger: { fontSize: 11, color: Colors.error, marginTop: 2 },
  content: { flex: 1 },
  contentContainer: { padding: Spacing.lg },
  card: {
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.lg,
    padding: Spacing.lg,
    marginBottom: Spacing.lg,
  },
  cardTitle: { fontSize: 20, fontWeight: "700", color: Colors.text },
  section: { marginBottom: Spacing.lg },
  sectionLabel: { fontSize: 13, color: Colors.textSecondary, marginBottom: Spacing.xs },
  sectionValue: { fontSize: 16, color: Colors.text, fontWeight: "500" },
  componentsList: {
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.md,
    overflow: "hidden",
  },
  componentRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  componentName: { fontSize: 15, color: Colors.text },
  componentAmount: { fontSize: 15, fontWeight: "600", color: Colors.text },
  emptyText: { fontSize: 14, color: Colors.textSecondary },
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: Spacing.xl },
  errorText: { color: Colors.error, fontSize: 16, marginBottom: Spacing.md },
  retryBtn: {
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    backgroundColor: Colors.primary,
    borderRadius: Layout.borderRadius.md,
  },
  retryBtnText: { color: "#fff", fontWeight: "600" },

  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "flex-end",
  },
  modalContent: {
    backgroundColor: Colors.background,
    borderTopLeftRadius: Layout.borderRadius.xl,
    borderTopRightRadius: Layout.borderRadius.xl,
    maxHeight: "90%",
  },
  modalHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: Spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  modalTitle: { fontSize: 18, fontWeight: "700", color: Colors.text },
  modalBody: { padding: Spacing.lg, maxHeight: 400 },
  modalFooter: {
    flexDirection: "row",
    gap: Spacing.md,
    padding: Spacing.lg,
    borderTopWidth: 1,
    borderTopColor: Colors.borderLight,
  },
  inputLabel: { fontSize: 14, fontWeight: "600", color: Colors.text, marginBottom: Spacing.sm },
  input: {
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: Layout.borderRadius.md,
    padding: Spacing.md,
    fontSize: 16,
    marginBottom: Spacing.md,
  },
  componentHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  componentFormRow: { flexDirection: "row", alignItems: "center", marginBottom: Spacing.sm },
  componentInput: { flex: 1, marginRight: Spacing.sm },
  amountInput: { width: 90, marginRight: Spacing.sm },
  optionalRow: { flexDirection: "row", alignItems: "center", marginRight: Spacing.sm },
  optionalLabel: { fontSize: 12, color: Colors.textSecondary, marginRight: Spacing.xs },
  removeBtn: { padding: Spacing.sm },
  addComponentBtn: { flexDirection: "row", alignItems: "center" },
  addComponentText: { fontSize: 14, color: Colors.primary, marginLeft: Spacing.xs },
  cancelBtn: { flex: 1, padding: Spacing.md, alignItems: "center" },
  cancelBtnText: { fontSize: 16, color: Colors.textSecondary },
  submitBtn: { flex: 1, backgroundColor: Colors.primary, padding: Spacing.md, borderRadius: Layout.borderRadius.md, alignItems: "center" },
  submitBtnDisabled: { opacity: 0.7 },
  submitBtnText: { fontSize: 16, fontWeight: "600", color: Colors.background },
});
