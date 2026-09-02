import type { Category } from "@/lib/types";

interface Props {
  categories: Category[];
  selected: string | null;
  onSelect: (category: string | null) => void;
}

export default function CategoryTabs({ categories, selected, onSelect }: Props) {
  const totalCount = categories.reduce((sum, c) => sum + c.product_count, 0);

  return (
    <div className="flex flex-wrap gap-2">
      <button
        onClick={() => onSelect(null)}
        className={`rounded-full border px-3 py-1 text-sm ${
          selected === null
            ? "border-black bg-black text-white"
            : "border-gray-300 text-gray-700 hover:border-gray-400"
        }`}
      >
        All ({totalCount})
      </button>
      {categories.map((c) => (
        <button
          key={c.category}
          onClick={() => onSelect(c.category)}
          className={`rounded-full border px-3 py-1 text-sm capitalize ${
            selected === c.category
              ? "border-black bg-black text-white"
              : "border-gray-300 text-gray-700 hover:border-gray-400"
          }`}
        >
          {c.category.replace("_", " ")} ({c.product_count})
        </button>
      ))}
    </div>
  );
}
