import { TopBar } from "@/components/live/top-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { VisuallyHidden } from "@/components/ui/visually-hidden";

/**
 * The plan page before its first answer, in the shape of what is coming: the title block, the
 * control bar with the cost line, and the five lanes in place (cards on the phone, columns from
 * 1080 px). Server-safe: loading.tsx renders it during navigation.
 */
export function PlanSkeleton() {
  return (
    <div aria-busy="true">
      <VisuallyHidden>Carico il piano…</VisuallyHidden>
      <TopBar />
      <div className="lg:border-b lg:border-rule">
        <div className="mx-auto max-w-page lg:grid lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end lg:gap-6 lg:px-7 lg:pt-4 lg:pb-3.5">
          <div className="px-4 pt-1 pb-3 lg:p-0">
            <Skeleton className="h-7 w-3/5 max-w-80 lg:h-8" />
            <Skeleton className="mt-2 h-4 w-4/5 max-w-[26rem]" />
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-3 border-b border-rule px-4 pt-3 pb-3.5 lg:grid-cols-[auto_minmax(15rem,18.75rem)_auto] lg:gap-x-7 lg:border-0 lg:p-0">
            <div className="grid gap-1.5">
              <Skeleton className="h-5 w-24" />
              <Skeleton className="h-4 w-28" />
            </div>
            <div className="col-span-2 row-start-2 grid gap-2 lg:col-span-1 lg:col-start-2 lg:row-start-1">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-1.5 w-full" />
            </div>
            <div className="flex gap-2 lg:col-start-3 lg:row-start-1">
              <Skeleton shape="round" className="h-10 w-28" />
              <Skeleton shape="round" className="size-10" />
            </div>
          </div>
        </div>
      </div>
      <div className="mx-auto mt-3 grid max-w-page gap-2.5 px-4 pb-8 lg:mt-4 lg:grid-cols-[minmax(0,1.3fr)_repeat(4,minmax(0,1fr))] lg:gap-x-3.5 lg:px-7">
        {[0, 1, 2, 3, 4].map((lane) => (
          <div
            key={lane}
            className="flex items-center gap-2.5 rounded-md border border-rule bg-surface px-3.5 py-3 lg:items-start lg:border-0 lg:border-b lg:bg-transparent lg:px-0 lg:pt-1 lg:pb-3"
          >
            <Skeleton shape="round" className="size-[30px] shrink-0 lg:size-[34px]" />
            <div className="grid flex-1 gap-1.5">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-3.5 w-16" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
