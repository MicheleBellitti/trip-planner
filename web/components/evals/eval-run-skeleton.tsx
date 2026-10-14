import { AppHeader } from "@/components/nav/app-header";
import { Skeleton } from "@/components/ui/skeleton";
import { VisuallyHidden } from "@/components/ui/visually-hidden";

/** The run page before its first answer, in the shape of what is coming: the title and its line of
 * facts, the verdict card with its figures, the first request. Server-safe: loading.tsx renders
 * it during navigation. */
export function EvalRunSkeleton() {
  return (
    <div aria-busy="true">
      <VisuallyHidden>Carico la valutazione…</VisuallyHidden>
      <AppHeader current="evals" />
      <main className="mx-auto max-w-page px-4 pt-5 pb-16 lg:px-7 lg:pt-7">
        <Skeleton className="mt-2.5 w-24" />
        <div className="mt-4 max-w-[64rem]">
          <Skeleton className="h-7 w-4/5 max-w-[26rem] lg:h-8" />
          <Skeleton className="mt-3 h-4 w-3/5 max-w-[22rem]" />
          <div className="mt-5 rounded-md border border-rule bg-surface px-4 py-4 lg:px-5">
            <Skeleton className="h-5 w-28" />
            <Skeleton className="mt-2 h-4 w-4/5 max-w-[30rem]" />
            <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4 border-t border-rule pt-4 sm:grid-cols-3 lg:grid-cols-6">
              {[0, 1, 2, 3, 4, 5].map((fact) => (
                <div key={fact} className="grid gap-1.5">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-5 w-14" />
                </div>
              ))}
            </div>
          </div>
          <Skeleton className="mt-9 h-6 w-56" />
          <Skeleton shape="block" className="mt-3 h-24 w-full max-w-[48rem]" />
        </div>
      </main>
    </div>
  );
}
