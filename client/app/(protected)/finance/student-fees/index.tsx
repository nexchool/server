import React, { useState, useMemo, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  TextInput,
  SafeAreaView,
  FlatList,
  ScrollView,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import {
  useStudentFees,
  useAcademicYears,
  useClasses,
} from "@/modules/finance/hooks/useFinance";
import { useAcademicYearContext } from "@/modules/academics/context/AcademicYearContext";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";
import { ClassSelect } from "@/common/components/ClassSelect";

function formatCurrency(n: number) {
  return `₹${n.toLocaleString("en-IN")}`;
}

function formatDate(s: string) {
  try {
    return new Date(s).toLocaleDateString("en-IN");
  } catch {
    return s;
  }
}

const STATUS_OPTIONS = [
  { value: "", label: "All" },
  { value: "overdue", label: "Overdue" },
  { value: "unpaid", label: "Unpaid" },
  { value: "partial", label: "Partial" },
  { value: "paid", label: "Paid" },
];

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    paid: Colors.success,
    partial: Colors.warning,
    unpaid: Colors.textSecondary,
    overdue: Colors.error,
  };
  return (
    <View style={[styles.badge, { backgroundColor: colors[status] || Colors.textSecondary }]}>
      <Text style={styles.badgeText}>{status}</Text>
    </View>
  );
}

export default function StudentFeesPage() {
  const router = useRouter();
  const { selectedAcademicYearId: contextYearId } = useAcademicYearContext();
  const [academicYearId, setAcademicYearId] = useState<string>("");
  const [classId, setClassId] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [search, setSearch] = useState("");

  const { data: academicYears = [] } = useAcademicYears(false);
  const { data: classes = [] } = useClasses();

  useEffect(() => {
    if (contextYearId) setAcademicYearId((prev) => (prev === "" ? contextYearId : prev));
  }, [contextYearId]);

  const { data: studentFees = [], isLoading, error, refetch, isRefetching } = useStudentFees({
    academic_year_id: academicYearId || undefined,
    class_id: classId || undefined,
    status: status || undefined,
    search: search.trim() || undefined,
  });

  const classOptions = useMemo(
    () =>
      classes.map((c) => ({
        id: c.id,
        label: c.section ? `${c.name}-${c.section}` : c.name ?? c.id,
        name: c.name,
        section: c.section,
      })),
    [classes]
  );

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.errorText}>
          {error instanceof Error ? error.message : "Failed to load"}
        </Text>
      </View>
    );
  }

  const renderFeeItem = ({ item: sf }: { item: (typeof studentFees)[0] }) => (
    <TouchableOpacity
      style={styles.listItem}
      onPress={() => router.push(`/(protected)/finance/student-fees/${sf.id}` as any)}
      activeOpacity={0.7}
    >
      <View style={styles.avatar}>
        <Ionicons name="person" size={24} color={Colors.primary} />
      </View>
      <View style={styles.content}>
        <Text style={styles.name}>{sf.student_name ?? "—"}</Text>
        <Text style={styles.info}>
          {sf.fee_structure_name ?? "—"} • Due {formatDate(sf.due_date)}
        </Text>
        <View style={styles.metaRow}>
          <Text style={styles.amountText}>{formatCurrency(sf.total_amount)}</Text>
          <Text style={styles.paidText}>{formatCurrency(sf.paid_amount)} paid</Text>
          <StatusBadge status={sf.status} />
        </View>
      </View>
      <Ionicons name="chevron-forward" size={20} color={Colors.textSecondary} />
    </TouchableOpacity>
  );

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backIcon}>
          <Ionicons name="arrow-back" size={24} color={Colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Student Fees</Text>
      </View>

      {/* Search */}
      <View style={styles.searchContainer}>
        <Ionicons name="search" size={20} color={Colors.textSecondary} style={styles.searchIcon} />
        <TextInput
          style={styles.searchInput}
          value={search}
          onChangeText={setSearch}
          placeholder="Search by name or admission number..."
          placeholderTextColor={Colors.textSecondary}
        />
        {search.length > 0 && (
          <TouchableOpacity onPress={() => setSearch("")}>
            <Ionicons name="close-circle" size={20} color={Colors.textSecondary} />
          </TouchableOpacity>
        )}
      </View>

      {/* Filter bar */}
      <View style={styles.filterBar}>
        <Text style={styles.filterLabel}>Academic Year</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterRow}>
          <TouchableOpacity
            style={[styles.filterChip, !academicYearId && styles.filterChipActive]}
            onPress={() => setAcademicYearId("")}
          >
            <Text style={[styles.filterChipText, !academicYearId && styles.filterChipTextActive]}>
              All
            </Text>
          </TouchableOpacity>
          {academicYears.map((ay) => (
            <TouchableOpacity
              key={ay.id}
              style={[styles.filterChip, academicYearId === ay.id && styles.filterChipActive]}
              onPress={() => setAcademicYearId(academicYearId === ay.id ? "" : ay.id)}
            >
              <Text
                style={[
                  styles.filterChipText,
                  academicYearId === ay.id && styles.filterChipTextActive,
                ]}
              >
                {ay.name}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>

        <Text style={styles.filterLabel}>Class</Text>
        <ClassSelect
          value={classId || null}
          onChange={(id) => setClassId(id ?? "")}
          options={classOptions}
          allowEmpty
          emptyLabel="All"
        />

        <Text style={styles.filterLabel}>Status</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterRow}>
          {STATUS_OPTIONS.map((opt) => (
            <TouchableOpacity
              key={opt.value || "all"}
              style={[styles.filterChip, status === opt.value && styles.filterChipActive]}
              onPress={() => setStatus(opt.value)}
            >
              <Text
                style={[
                  styles.filterChipText,
                  status === opt.value && styles.filterChipTextActive,
                ]}
              >
                {opt.label}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>

      </View>

      {isLoading && studentFees.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={Colors.primary} />
        </View>
      ) : (
        <FlatList
          data={studentFees}
          keyExtractor={(item) => item.id}
          renderItem={renderFeeItem}
          contentContainerStyle={styles.listContent}
          refreshControl={
            <RefreshControl refreshing={isRefetching} onRefresh={refetch} />
          }
          ListEmptyComponent={
            <View style={styles.emptyState}>
              <Ionicons
                name={search ? "search-outline" : "people-outline"}
                size={48}
                color={Colors.textTertiary}
              />
              <Text style={styles.emptyTitle}>
                {search ? "No results" : "No student fees yet"}
              </Text>
              <Text style={styles.emptySubtext}>
                {search
                  ? "Try a different search or clear filters"
                  : "Assign fee structures to students to see them here"}
              </Text>
              {!search && (
                <TouchableOpacity
                  style={styles.emptyCta}
                  onPress={() => router.push("/(protected)/finance/structures" as any)}
                >
                  <Text style={styles.emptyCtaText}>Go to Fee Structures</Text>
                  <Ionicons name="arrow-forward" size={18} color="#fff" />
                </TouchableOpacity>
              )}
            </View>
          }
        />
      )}
    </SafeAreaView>
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
  headerTitle: { fontSize: 24, fontWeight: "bold", color: Colors.text },
  searchContainer: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.md,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    margin: Spacing.md,
    borderWidth: 1,
    borderColor: Colors.borderLight,
  },
  searchIcon: { marginRight: Spacing.sm },
  searchInput: { flex: 1, fontSize: 16, color: Colors.text, padding: Spacing.sm },
  filterBar: {
    paddingHorizontal: Spacing.md,
    paddingBottom: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  filterLabel: { fontSize: 14, color: Colors.textSecondary, marginBottom: Spacing.sm },
  filterRow: { marginBottom: Spacing.md },
  filterChip: {
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    borderRadius: Layout.borderRadius.md,
    backgroundColor: Colors.backgroundSecondary,
    marginRight: Spacing.sm,
  },
  filterChipActive: { backgroundColor: Colors.primary },
  filterChipText: { fontSize: 14, color: Colors.text },
  filterChipTextActive: { fontSize: 14, color: Colors.background, fontWeight: "600" },
  listContent: { padding: Spacing.md },
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: Spacing.xl },
  emptyState: { alignItems: "center", paddingVertical: Spacing.xxl },
  emptyTitle: { fontSize: 18, fontWeight: "600", color: Colors.text, marginTop: Spacing.md },
  emptySubtext: {
    fontSize: 14,
    color: Colors.textSecondary,
    marginTop: Spacing.xs,
    textAlign: "center",
    paddingHorizontal: Spacing.xl,
  },
  emptyCta: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.sm,
    marginTop: Spacing.lg,
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    backgroundColor: Colors.primary,
    borderRadius: Layout.borderRadius.md,
  },
  emptyCtaText: { color: "#fff", fontWeight: "600", fontSize: 15 },
  errorText: { color: Colors.error, fontSize: 16 },
  listItem: {
    flexDirection: "row",
    alignItems: "center",
    padding: Spacing.md,
    backgroundColor: Colors.background,
    borderRadius: Layout.borderRadius.md,
    marginBottom: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.borderLight,
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: Colors.backgroundSecondary,
    alignItems: "center",
    justifyContent: "center",
    marginRight: Spacing.md,
  },
  content: { flex: 1 },
  name: { fontSize: 16, fontWeight: "600", color: Colors.text, marginBottom: 2 },
  info: { fontSize: 14, color: Colors.textSecondary },
  metaRow: { flexDirection: "row", alignItems: "center", marginTop: Spacing.xs, gap: Spacing.sm },
  amountText: { fontSize: 14, fontWeight: "600", color: Colors.text },
  paidText: { fontSize: 12, color: Colors.success },
  badge: {
    paddingHorizontal: Spacing.sm,
    paddingVertical: 2,
    borderRadius: Layout.borderRadius.sm,
  },
  badgeText: { fontSize: 11, fontWeight: "600", color: Colors.background },
});
