import React, { useMemo } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Pressable,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useStudentFees, useRecentPayments } from "@/modules/finance/hooks/useFinance";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";

function formatCurrency(n: number) {
  return `₹${n.toLocaleString("en-IN")}`;
}

export default function FinanceDashboardPage() {
  const router = useRouter();
  const { data: studentFees = [], isLoading, error, refetch, isRefetching } = useStudentFees();
  const { data: recentPayments = [] } = useRecentPayments(10);

  const stats = useMemo(() => {
    let totalExpected = 0;
    let totalCollected = 0;
    let overdueCount = 0;
    for (const sf of studentFees) {
      totalExpected += sf.total_amount ?? 0;
      totalCollected += sf.paid_amount ?? 0;
      if (sf.status === "overdue") overdueCount++;
    }
    const totalOutstanding = totalExpected - totalCollected;
    return { totalExpected, totalCollected, totalOutstanding, overdueCount };
  }, [studentFees]);

  if (error) {
    return (
      <View style={styles.center}>
        <Ionicons name="alert-circle-outline" size={48} color={Colors.error} style={{ marginBottom: Spacing.md }} />
        <Text style={styles.errorText}>
          {error instanceof Error ? error.message : "Failed to load"}
        </Text>
        <TouchableOpacity style={styles.retryBtn} onPress={() => refetch()}>
          <Text style={styles.retryBtnText}>Try again</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.contentContainer}
      refreshControl={
        <RefreshControl refreshing={isRefetching} onRefresh={refetch} />
      }
    >
      <View style={styles.header}>
        <Text style={styles.title}>Finance</Text>
        <Text style={styles.subtitle}>Track fees and collect payments</Text>
      </View>

      {isLoading && studentFees.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={Colors.primary} />
          <Text style={styles.loadingText}>Loading your finance data…</Text>
        </View>
      ) : (
        <View style={styles.content}>
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Summary</Text>
            <Text style={styles.sectionHint}>Overview of fee collection this term</Text>
            <View style={styles.statsGrid}>
              <View style={styles.statCard}>
                <View style={styles.statIconWrap}>
                  <Ionicons name="document-text-outline" size={24} color={Colors.primary} />
                </View>
                <Text style={styles.statValue} numberOfLines={1}>
                  {formatCurrency(stats.totalExpected)}
                </Text>
                <Text style={styles.statLabel}>Total Expected</Text>
              </View>
              <View style={[styles.statCard, styles.statCardSuccess]}>
                <View style={styles.statIconWrap}>
                  <Ionicons name="checkmark-circle-outline" size={24} color={Colors.success} />
                </View>
                <Text style={styles.statValue} numberOfLines={1}>
                  {formatCurrency(stats.totalCollected)}
                </Text>
                <Text style={styles.statLabel}>Total Collected</Text>
              </View>
            </View>
            <View style={styles.statsGrid}>
              <View style={[styles.statCard, styles.statCardWarning]}>
                <View style={styles.statIconWrap}>
                  <Ionicons name="hourglass-outline" size={24} color={Colors.warning} />
                </View>
                <Text style={styles.statValue} numberOfLines={1}>
                  {formatCurrency(stats.totalOutstanding)}
                </Text>
                <Text style={styles.statLabel}>Total Outstanding</Text>
              </View>
              <View style={[styles.statCard, stats.overdueCount > 0 && styles.statCardDanger]}>
                <View style={styles.statIconWrap}>
                  <Ionicons name="alert-circle-outline" size={24} color={Colors.error} />
                </View>
                <Text style={styles.statValue} numberOfLines={1}>
                  {stats.overdueCount}
                </Text>
                <Text style={styles.statLabel}>Overdue</Text>
              </View>
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Quick Actions</Text>
            <Text style={styles.sectionHint}>Jump to common tasks</Text>
            <Pressable
              style={({ pressed }) => [styles.linkCard, pressed && styles.linkCardPressed]}
              onPress={() => router.push("/(protected)/finance/structures" as any)}
            >
              <View style={styles.cardContent}>
                <View style={[styles.cardIcon, styles.cardIconPrimary]}>
                  <Ionicons name="layers-outline" size={26} color={Colors.primary} />
                </View>
                <View style={styles.linkText}>
                  <Text style={styles.linkTitle}>Fee Structures</Text>
                  <Text style={styles.linkSubtitle}>Create and manage fee structures</Text>
                </View>
              </View>
              <Ionicons name="chevron-forward" size={22} color={Colors.textSecondary} />
            </Pressable>
            <Pressable
              style={({ pressed }) => [styles.linkCard, pressed && styles.linkCardPressed]}
              onPress={() => router.push("/(protected)/finance/student-fees" as any)}
            >
              <View style={styles.cardContent}>
                <View style={[styles.cardIcon, styles.cardIconPrimary]}>
                  <Ionicons name="people-outline" size={26} color={Colors.primary} />
                </View>
                <View style={styles.linkText}>
                  <Text style={styles.linkTitle}>Student Fees</Text>
                  <Text style={styles.linkSubtitle}>View fees and record payments</Text>
                </View>
              </View>
              <Ionicons name="chevron-forward" size={22} color={Colors.textSecondary} />
            </Pressable>
          </View>

          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <View>
                <Text style={styles.sectionTitle}>Recent Payments</Text>
                <Text style={styles.sectionHint}>Latest collections</Text>
              </View>
              {recentPayments.length > 0 && (
                <TouchableOpacity
                  onPress={() => router.push("/(protected)/finance/student-fees" as any)}
                  hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
                >
                  <Text style={styles.viewAllText}>View all</Text>
                </TouchableOpacity>
              )}
            </View>
            {recentPayments.length === 0 ? (
              <View style={styles.emptyCard}>
                <Ionicons name="card-outline" size={40} color={Colors.textTertiary} />
                <Text style={styles.emptyTitle}>No recent payments</Text>
                <Text style={styles.emptySubtitle}>
                  Payments you record will appear here
                </Text>
                <TouchableOpacity
                  style={styles.emptyCta}
                  onPress={() => router.push("/(protected)/finance/student-fees" as any)}
                >
                  <Text style={styles.emptyCtaText}>Go to Student Fees</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <View style={styles.recentList}>
                {recentPayments.map((p, i) => (
                  <View
                    key={p.id}
                    style={[
                      styles.paymentRow,
                      i === recentPayments.length - 1 && styles.paymentRowLast,
                    ]}
                  >
                    <View style={styles.paymentAvatar}>
                      <Text style={styles.paymentAvatarText}>
                        {(p.student_name ?? "?").charAt(0).toUpperCase()}
                      </Text>
                    </View>
                    <View style={styles.paymentInfo}>
                      <Text style={styles.paymentStudent}>
                        {p.student_name ?? "Unknown"}
                      </Text>
                      <Text style={styles.paymentDate}>
                        {new Date(p.created_at).toLocaleDateString("en-IN", {
                          day: "numeric",
                          month: "short",
                        })}
                      </Text>
                    </View>
                    <Text style={styles.paymentAmount}>{formatCurrency(p.amount)}</Text>
                  </View>
                ))}
              </View>
            )}
          </View>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  contentContainer: {
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.xl,
    paddingBottom: Spacing.lg,
  },
  header: { paddingBottom: Spacing.lg, marginBottom: Spacing.sm },
  title: { fontSize: 28, fontWeight: "700", color: Colors.text },
  subtitle: { fontSize: 15, color: Colors.textSecondary },
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: Spacing.xl },
  loadingText: { marginTop: Spacing.md, color: Colors.textSecondary, fontSize: 14 },
  errorText: { color: Colors.error, fontSize: 16, textAlign: "center" },
  retryBtn: {
    marginTop: Spacing.lg,
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    backgroundColor: Colors.primary,
    borderRadius: Layout.borderRadius.md,
  },
  retryBtnText: { color: "#fff", fontWeight: "600", fontSize: 15 },
  content: {},
  section: { marginBottom: Spacing.xl },
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: Spacing.md,
  },
  sectionTitle: { fontSize: 18, fontWeight: "600", color: Colors.text },
  sectionHint: { fontSize: 13, color: Colors.textSecondary, marginTop: 2 },
  viewAllText: { fontSize: 14, fontWeight: "600", color: Colors.primary },
  statsGrid: { flexDirection: "row", gap: Spacing.md, marginBottom: Spacing.md },
  statCard: {
    flex: 1,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.lg,
    padding: Spacing.lg,
    alignItems: "center",
  },
  statCardSuccess: { borderLeftWidth: 3, borderLeftColor: Colors.success },
  statCardWarning: { borderLeftWidth: 3, borderLeftColor: Colors.warning },
  statCardDanger: { borderLeftWidth: 3, borderLeftColor: Colors.error },
  statIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: Colors.background,
    alignItems: "center",
    justifyContent: "center",
  },
  statValue: { fontSize: 16, fontWeight: "700", color: Colors.text, marginTop: Spacing.sm },
  statLabel: { fontSize: 12, color: Colors.textSecondary, marginTop: Spacing.xs },
  linkCard: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.lg,
    padding: Spacing.lg,
    marginBottom: Spacing.md,
  },
  linkCardPressed: { opacity: 0.85 },
  cardContent: { flexDirection: "row", alignItems: "center", flex: 1 },
  cardIcon: {
    width: 52,
    height: 52,
    borderRadius: Layout.borderRadius.md,
    alignItems: "center",
    justifyContent: "center",
    marginRight: Spacing.md,
  },
  cardIconPrimary: { backgroundColor: "rgba(0,0,0,0.06)" },
  linkText: { flex: 1 },
  linkTitle: { fontSize: 16, fontWeight: "600", color: Colors.text, marginBottom: 2 },
  linkSubtitle: { fontSize: 13, color: Colors.textSecondary },
  emptyCard: {
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.lg,
    padding: Spacing.xl,
    alignItems: "center",
  },
  emptyTitle: { fontSize: 16, fontWeight: "600", color: Colors.text, marginTop: Spacing.md },
  emptySubtitle: { fontSize: 14, color: Colors.textSecondary, marginTop: Spacing.xs },
  emptyCta: {
    marginTop: Spacing.lg,
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.sm,
    backgroundColor: Colors.primary,
    borderRadius: Layout.borderRadius.md,
  },
  emptyCtaText: { color: "#fff", fontWeight: "600", fontSize: 14 },
  recentList: {
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.lg,
    overflow: "hidden",
  },
  paymentRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: Spacing.md,
    paddingHorizontal: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  paymentRowLast: { borderBottomWidth: 0 },
  paymentAvatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: Colors.borderLight,
    alignItems: "center",
    justifyContent: "center",
    marginRight: Spacing.md,
  },
  paymentAvatarText: { fontSize: 16, fontWeight: "600", color: Colors.textSecondary },
  paymentInfo: { flex: 1 },
  paymentStudent: { fontSize: 15, fontWeight: "500", color: Colors.text },
  paymentDate: { fontSize: 12, color: Colors.textSecondary, marginTop: 2 },
  paymentAmount: { fontSize: 16, fontWeight: "600", color: Colors.success },
});
