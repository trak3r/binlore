let cleanupTable: (() => void) | null = null

function initEpisodesTable() {
  const table = document.getElementById("episodes-table")
  if (!table) return

  if (cleanupTable) {
    cleanupTable()
    cleanupTable = null
  }

  const searchInput = document.getElementById("episode-search") as HTMLInputElement | null
  const statusFilter = document.getElementById("status-filter") as HTMLSelectElement | null
  const pageSizeSelect = document.getElementById("page-size") as HTMLSelectElement | null
  const prevBtn = document.getElementById("btn-prev") as HTMLButtonElement | null
  const nextBtn = document.getElementById("btn-next") as HTMLButtonElement | null
  const pageInfo = document.getElementById("page-info")

  const allRows = Array.from(table.querySelectorAll("tbody tr")) as HTMLTableRowElement[]
  let currentPage = 1

  function filterAndPaginate(shouldScroll: boolean = false) {
    const query = searchInput ? searchInput.value.toLowerCase().trim() : ""
    const status = statusFilter ? statusFilter.value : "all"
    const pageSizeVal = pageSizeSelect ? pageSizeSelect.value : "50"
    const pageSize = pageSizeVal === "all" ? allRows.length : parseInt(pageSizeVal, 10)

    const matchingRows = allRows.filter((row) => {
      const rowStatus = row.getAttribute("data-status")
      const rowTitle = row.getAttribute("data-title") || ""
      const rowDate = row.getAttribute("data-date") || ""
      const rowVod = row.getAttribute("data-vod-id") || ""
      const matchesStatus = status === "all" || rowStatus === status
      const matchesSearch =
        !query ||
        rowTitle.indexOf(query) !== -1 ||
        rowDate.indexOf(query) !== -1 ||
        rowVod.indexOf(query) !== -1
      return matchesStatus && matchesSearch
    })

    const totalPages = Math.max(1, Math.ceil(matchingRows.length / (pageSize || 1)))
    if (currentPage > totalPages) currentPage = totalPages
    if (currentPage < 1) currentPage = 1

    const startIdx = (currentPage - 1) * pageSize
    const endIdx = startIdx + pageSize

    allRows.forEach((row) => {
      row.style.display = "none"
    })

    matchingRows.slice(startIdx, endIdx).forEach((row) => {
      row.style.display = ""
    })

    if (pageInfo) {
      if (matchingRows.length === 0) {
        pageInfo.textContent = "0 matching streams"
      } else {
        pageInfo.textContent = `Page ${currentPage} of ${totalPages} (${matchingRows.length} streams)`
      }
    }
    if (prevBtn) prevBtn.disabled = currentPage <= 1
    if (nextBtn) nextBtn.disabled = currentPage >= totalPages || matchingRows.length === 0

    if (shouldScroll) {
      table.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }

  const onSearch = () => {
    currentPage = 1
    filterAndPaginate(false)
  }
  const onStatusChange = () => {
    currentPage = 1
    filterAndPaginate(false)
  }
  const onPageSizeChange = () => {
    currentPage = 1
    filterAndPaginate(false)
  }
  const onPrev = () => {
    if (currentPage > 1) {
      currentPage--
      filterAndPaginate(true)
    }
  }
  const onNext = () => {
    currentPage++
    filterAndPaginate(true)
  }

  if (searchInput) searchInput.addEventListener("input", onSearch)
  if (statusFilter) statusFilter.addEventListener("change", onStatusChange)
  if (pageSizeSelect) pageSizeSelect.addEventListener("change", onPageSizeChange)
  if (prevBtn) prevBtn.addEventListener("click", onPrev)
  if (nextBtn) nextBtn.addEventListener("click", onNext)

  cleanupTable = () => {
    if (searchInput) searchInput.removeEventListener("input", onSearch)
    if (statusFilter) statusFilter.removeEventListener("change", onStatusChange)
    if (pageSizeSelect) pageSizeSelect.removeEventListener("change", onPageSizeChange)
    if (prevBtn) prevBtn.removeEventListener("click", onPrev)
    if (nextBtn) nextBtn.removeEventListener("click", onNext)
  }

  if (typeof window.addCleanup === "function") {
    window.addCleanup(cleanupTable)
  }

  filterAndPaginate(false)
}

document.addEventListener("nav", () => {
  initEpisodesTable()
})

if (document.readyState !== "loading") {
  initEpisodesTable()
} else {
  document.addEventListener("DOMContentLoaded", () => {
    initEpisodesTable()
  })
}
