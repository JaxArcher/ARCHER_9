---
name: canvas_rendering
description: Create visual charts, tables, and diagrams to display data
category: visualization
---

# Canvas Rendering Tools

## create_chart

Create an interactive chart to visualize numerical data.

**Use when:** Data would be clearer as a visual than as text. Numbers, comparisons, trends.

**Parameters:**
- chart_type: 'pie' | 'bar' | 'line' | 'doughnut'
- title: string - Chart title
- data: object - Key-value pairs where keys are labels, values are numbers

**Example input:**
{
  chart_type: pie,
  title: Monthly Expenses,
  data: {
    Rent: 1200,
    Food: 400,
    Transport: 150
  }
}

---

## create_table

Create a formatted table for structured data with rows and columns.

**Use when:** Displaying structured data, comparisons, lists with multiple attributes.

**Parameters:**
- title: string - Table title
- headers: array of strings - Column headers
- rows: array of arrays - Table data rows

**Example input:**
{
  title: Workout Log,
  headers: [Exercise, Sets, Reps, Weight],
  rows: [
    [Bench Press, 3, 10, 185 lbs],
    [Squats, 4, 8, 225 lbs]
  ]
}
